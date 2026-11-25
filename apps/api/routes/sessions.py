"""
Session Ingestion and Telemetry Retrieval REST Endpoints.

A "session" is ONE PAGE VISIT (session_id == page_visit_id). Collectors send
delta chunks with an increasing ``seq``; see IngestSessionRequest for the
protocol and packages.database.repository.ingest_chunk for the rules.
"""

import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.database.db import get_db
from packages.database.models import SessionRecord, SiteRecord, VerdictHistory, SessionFeedback
from packages.database.schemas import (
    IngestSessionRequest,
    ClassificationResponse,
    SessionSummary,
    SessionDetailResponse,
    SessionFeedbackRequest,
    SessionFeedbackResponse,
)
from apps.api.dependencies import get_detection_engine, DecisionEngine
from apps.api.config import settings
from apps.api.routes.ws import ws_manager
from packages.database.repository import build_session_summary, ingest_chunk, IngestError, apply_source_filter

router = APIRouter(prefix="/api/v1/sessions", tags=["Sessions"])
logger = logging.getLogger("websense.ingest")


# ─── Rate limiting ───────────────────────────────────────────────────────────
# Per-session throttle is the primary control: one page visit sends a chunk
# every ~5 s, so 60/min leaves 5x headroom for retries. A coarse per-IP guard
# protects against floods but is high enough for many tabs behind one NAT.

_WINDOW_SEC = 60.0
_PRUNE_EVERY_SEC = 60.0


class _SlidingWindowLimiter:
    def __init__(self, limit: int):
        self.limit = limit
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_prune = time.monotonic()

    def hit(self, key: str) -> bool:
        """Records a hit; returns False if the key is over its limit."""
        now = time.monotonic()
        cutoff = now - _WINDOW_SEC
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if now - self._last_prune > _PRUNE_EVERY_SEC:
                self._prune(cutoff)
                self._last_prune = now
            return True

    def _prune(self, cutoff: float) -> None:
        stale = [k for k, q in self._hits.items() if not q or q[-1] <= cutoff]
        for k in stale:
            del self._hits[k]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_session_limiter = _SlidingWindowLimiter(settings.INGEST_MAX_CHUNKS_PER_SESSION_PER_MIN)
_site_ip_limiter = _SlidingWindowLimiter(settings.INGEST_MAX_REQUESTS_PER_IP_PER_MIN)
_ip_limiter = _site_ip_limiter  # backward-compatible alias for test fixtures


def _client_ip(request: Request) -> str:
    if settings.TRUST_PROXY_HEADERS:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _validate_site_origin(site: SiteRecord, request: Request, require_origin_when_restricted: bool = True):
    """
    Validates that the incoming request origin is authorized for the given site.
    If allowed_origins is '*', all origins are permitted.
    """
    if not site.allowed_origins or site.allowed_origins == "*":
        return True

    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    if not origin:
        if require_origin_when_restricted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Origin header or Bearer API key required for site '{site.site_id}'."
            )
        return True

    parsed_origin = urlparse(origin)
    origin_host = f"{parsed_origin.scheme}://{parsed_origin.netloc}".rstrip("/")

    allowed_list = [o.strip().rstrip("/") for o in site.allowed_origins.split(",") if o.strip()]

    for allowed in allowed_list:
        if allowed == "*" or allowed == origin_host:
            return True
        # Check wildcard subdomains e.g. *.example.com
        if allowed.startswith("*."):
            suffix = allowed[1:]  # .example.com
            if parsed_origin.netloc.endswith(suffix):
                return True

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Origin '{origin_host}' is not authorized for site '{site.site_id}'."
    )


def verify_site_access(
    payload: IngestSessionRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[SiteRecord]:
    """
    Validates site_id + Origin (browser SDK) or Authorization: Bearer ws_live_... (server-to-server).
    """
    auth_header = request.headers.get("authorization", "")
    bearer_token = ""
    if auth_header.lower().startswith("bearer "):
        bearer_token = auth_header[7:].strip()

    site_id = payload.site_id
    site: Optional[SiteRecord] = None

    if site_id:
        site = db.query(SiteRecord).filter(SiteRecord.site_id == site_id).first()
        if not site:
            raise HTTPException(status_code=404, detail=f"Site ID '{site_id}' is not registered.")
        if not site.is_active:
            raise HTTPException(status_code=403, detail=f"Site '{site_id}' is currently deactivated.")

        if bearer_token:
            if not site.api_key or not secrets.compare_digest(bearer_token, site.api_key):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid API key for the specified site.",
                )
        else:
            _validate_site_origin(site, request)
    elif bearer_token:
        site = db.query(SiteRecord).filter(SiteRecord.api_key == bearer_token).first()
        if not site:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key.",
            )
        if not site.is_active:
            raise HTTPException(status_code=403, detail=f"Site '{site.site_id}' is currently deactivated.")

    return site


def _compute_mitigation_action(site: Optional[SiteRecord], predicted_label: str, risk_score: float) -> str:
    """Computes active mitigation action (ALLOW | CHALLENGE | BLOCK) from site policy."""
    if not site:
        return "ALLOW"
    threshold = site.risk_threshold if site.risk_threshold is not None else 80
    mode = (site.enforcement_mode or "monitor").lower()
    triggered = (risk_score >= threshold) or (predicted_label == "AGENTIC_AI")
    if not triggered or mode == "monitor":
        return "ALLOW"
    if mode == "block":
        return "BLOCK"
    if mode == "challenge":
        return "CHALLENGE"
    return "ALLOW"


def _send_webhook_alert(webhook_url: str, secret_key: str, payload: Dict) -> None:
    """Sends an HMAC-SHA256 signed webhook alert for high-risk detections."""
    try:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        sig = hmac.new(secret_key.encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-SentinelTrace-Signature": f"sha256={sig}",
        }
        httpx.post(webhook_url, content=body, headers=headers, timeout=3.0)
    except Exception as exc:
        logger.warning("webhook_delivery_failed url=%s err=%s", webhook_url, exc)


@router.post("", response_model=ClassificationResponse)
def ingest_session(
    payload: IngestSessionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    engine: DecisionEngine = Depends(get_detection_engine),
    site: Optional[SiteRecord] = Depends(verify_site_access),
):
    """
    Ingests one telemetry chunk for a page visit, rebuilds features from all
    chunks of that visit, runs the 5-layer detection engine and persists the
    verdict. Idempotent: re-sending the same (session_id, seq) returns the
    current verdict with ``duplicate=true`` and writes nothing.
    """
    site_id = site.site_id if site else payload.site_id

    # 1. Throttle: per page visit first, then per-(site_id, client_ip) tenant-isolated guard.
    if not _session_limiter.hit(payload.session_id):
        raise HTTPException(status_code=429, detail="Too many chunks for this session; slow down.")
    tenant_ip_key = f"{site_id or 'default'}:{_client_ip(request)}"
    if not _site_ip_limiter.hit(tenant_ip_key):
        raise HTTPException(status_code=429, detail="Too many requests for this site from this address.")

    # 2. Single idempotent write path. Retry once if a concurrent request won
    #    the race to create a child row (possible on PostgreSQL).
    for attempt in (1, 2):
        try:
            result = ingest_chunk(
                db, payload, site_id, engine,
                max_chunks_per_session=settings.INGEST_MAX_CHUNKS_PER_SESSION,
            )
            db.commit()
            break
        except IngestError as e:
            db.rollback()
            raise HTTPException(status_code=e.status_code, detail=e.detail)
        except IntegrityError:
            db.rollback()
            if attempt == 2:
                logger.exception("ingest_integrity_error session_id=%s", payload.session_id)
                raise HTTPException(status_code=409, detail="Concurrent write conflict; retry.")

    action = _compute_mitigation_action(
        site,
        result.get("predicted_label", "UNCERTAIN"),
        float(result.get("risk_score", 0.0)),
    )
    result["action"] = action

    if not result.get("duplicate") and not result.get("stale"):
        ws_event = {
            "session_id": result["session_id"],
            "site_id": site_id,
            "predicted_label": result["predicted_label"],
            "risk_score": result["risk_score"],
            "confidence": result["confidence"],
            "action": action,
            "timestamp": time.time(),
        }
        background_tasks.add_task(ws_manager.broadcast, ws_event)

        threshold = (site.risk_threshold if site and site.risk_threshold is not None else 80)
        is_high_risk = (float(result.get("risk_score", 0.0)) >= threshold) or (result.get("predicted_label") == "AGENTIC_AI")
        if site and site.webhook_url and is_high_risk:
            background_tasks.add_task(_send_webhook_alert, site.webhook_url, site.api_key or "", ws_event)

    return ClassificationResponse(**result)


@router.get("", response_model=List[SessionSummary])
def list_sessions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    label: Optional[str] = Query(None),
    site_id: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    journey_id: Optional[str] = Query(None, description="Only page visits of this tab journey"),
    db: Session = Depends(get_db)
):
    """Lists recent page visits (one row per visit) with optional filters."""
    query = db.query(SessionRecord).order_by(SessionRecord.created_at.desc())
    if label and label != "ALL":
        query = query.filter(SessionRecord.predicted_label == label)
    if site_id and site_id != "ALL":
        query = query.filter(SessionRecord.site_id == site_id)
    query = apply_source_filter(query, source)
    if journey_id:
        query = query.filter(SessionRecord.journey_id == journey_id)

    sessions = query.offset(offset).limit(limit).all()
    logger.info(
        "list_sessions returned=%d limit=%d offset=%d label=%s site=%s source=%s",
        len(sessions), limit, offset,
        label or "ALL", site_id or "ALL", source or "ALL",
    )
    return [build_session_summary(s) for s in sessions]


@router.get("/{session_id}/timeline")
def get_session_timeline(session_id: str, db: Session = Depends(get_db)):
    """Verdict after every accepted chunk of this page visit (confidence timeline)."""
    if not db.query(SessionRecord.session_id).filter(SessionRecord.session_id == session_id).first():
        raise HTTPException(status_code=404, detail="Session not found")
    rows = (
        db.query(VerdictHistory)
        .filter(VerdictHistory.session_id == session_id)
        .order_by(VerdictHistory.seq)
        .all()
    )
    points = [
        {
            "seq": r.seq,
            "label": r.label,
            "predicted_label": r.label,
            "confidence": r.confidence,
            "risk_score": r.risk_score,
            "event_count": r.event_count,
            "evidence": r.evidence or {},
            "model_version": r.model_version,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else None,
        }
        for r in rows
    ]
    return {
        "session_id": session_id,
        "points": points,
        "timeline": points,
    }


@router.get("/{session_id}/history", response_model=SessionDetailResponse)
def get_session_history(session_id: str, db: Session = Depends(get_db)):
    """Session history inspection endpoint (alias for get_session_detail)."""
    return get_session_detail(session_id=session_id, db=db)


@router.get("/{session_id}", response_model=SessionDetailResponse)
def get_session_detail(session_id: str, db: Session = Depends(get_db)):
    """Fetches full session details including 2D trajectory coordinates, features, and layer breakdown."""
    session = db.query(SessionRecord).filter(SessionRecord.session_id == session_id).first()
    if not session:
        logger.warning("session_detail_not_found session_id=%s", session_id)
        raise HTTPException(status_code=404, detail="Session not found")

    logger.info(
        "session_detail session_id=%s verdict=%s confidence=%.1f risk=%.1f site=%s",
        session_id,
        session.predicted_label or "-",
        session.confidence or 0.0,
        session.risk_score or 0.0,
        session.site_id or "-",
    )
    summary = build_session_summary(session)

    feat_dict = session.features.all_features_json if session.features and session.features.all_features_json else {}
    
    verdict_dict = {}
    if session.verdict:
        v = session.verdict
        verdict_dict = {
            "l1_rule_score": v.l1_rule_score,
            "l1_flags": v.l1_flags or [],
            "l2_ml_pred": v.l2_ml_pred,
            "l2_ml_confidence": v.l2_ml_confidence,
            "l2_ml_probabilities": v.l2_ml_probabilities or {},
            "l3_anomaly_score": v.l3_anomaly_score,
            "l3_is_anomaly": v.l3_is_anomaly,
            "l4_replay_similarity": v.l4_replay_similarity,
            "l4_matched_session_id": v.l4_matched_session_id,
            "l4_is_replay": v.l4_is_replay,
            "l5_context_valid": v.l5_context_valid,
            "l5_context_violations": v.l5_context_violations or [],
            "l5_status": v.l5_status or "not_applicable",
            "final_verdict": v.final_verdict,
            "confidence": v.confidence,
            "risk_score": v.risk_score,
            "contributing_signals": v.contributing_signals or [],
            "counter_signals": v.counter_signals or [],
            "human_explanation": v.human_explanation,
            "model_version": v.model_version
        }

    telem_dict = {}
    if session.telemetry:
        t = session.telemetry
        telem_dict = {
            "mouse_events": t.mouse_events or [],
            "keyboard_events": t.keyboard_events or [],
            "scroll_events": t.scroll_events or [],
            "click_events": t.click_events or [],
            "browser_signals": t.browser_signals or {},
            "task_actions": t.task_actions or []
        }

    return SessionDetailResponse(
        session=summary,
        features=feat_dict,
        verdict=verdict_dict,
        telemetry=telem_dict
    )


@router.post("/{session_id}/feedback", response_model=SessionFeedbackResponse, status_code=status.HTTP_201_CREATED)
def submit_session_feedback(
    session_id: str,
    payload: SessionFeedbackRequest,
    db: Session = Depends(get_db),
):
    """
    Allows analysts on /dashboard to override a misclassified session's label
    and record notes for active learning and drift monitoring.
    """
    session = db.query(SessionRecord).filter(SessionRecord.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    feedback = SessionFeedback(
        session_id=session_id,
        analyst_label=payload.analyst_label,
        notes=payload.notes,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)

    return SessionFeedbackResponse(
        id=feedback.id,
        session_id=feedback.session_id,
        analyst_label=feedback.analyst_label,
        notes=feedback.notes or "",
        created_at=feedback.created_at.isoformat() if feedback.created_at else "",
    )
