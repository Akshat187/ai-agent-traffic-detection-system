"""
Session Ingestion and Telemetry Retrieval REST Endpoints.

A "session" is ONE PAGE VISIT (session_id == page_visit_id). Collectors send
delta chunks with an increasing ``seq``; see IngestSessionRequest for the
protocol and packages.database.repository.ingest_chunk for the rules.
"""

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.database.db import get_db
from packages.database.models import SessionRecord, SiteRecord, VerdictHistory
from packages.database.schemas import (
    IngestSessionRequest,
    ClassificationResponse,
    SessionSummary,
    SessionDetailResponse
)
from apps.api.dependencies import get_detection_engine, DecisionEngine
from apps.api.config import settings
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
_ip_limiter = _SlidingWindowLimiter(settings.INGEST_MAX_REQUESTS_PER_IP_PER_MIN)


def _client_ip(request: Request) -> str:
    if settings.TRUST_PROXY_HEADERS:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _validate_site_origin(site: SiteRecord, request: Request):
    """
    Validates that the incoming request origin is authorized for the given site.
    If allowed_origins is '*', all origins are permitted.
    """
    if not site.allowed_origins or site.allowed_origins == "*":
        return True

    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    if not origin:
        # Same-origin or non-browser client
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


@router.post("", response_model=ClassificationResponse)
def ingest_session(
    payload: IngestSessionRequest,
    request: Request,
    db: Session = Depends(get_db),
    engine: DecisionEngine = Depends(get_detection_engine)
):
    """
    Ingests one telemetry chunk for a page visit, rebuilds features from all
    chunks of that visit, runs the 5-layer detection engine and persists the
    verdict. Idempotent: re-sending the same (session_id, seq) returns the
    current verdict with ``duplicate=true`` and writes nothing.
    """
    # 1. Throttle: per page visit first, then a coarse per-IP guard.
    if not _session_limiter.hit(payload.session_id):
        raise HTTPException(status_code=429, detail="Too many chunks for this session; slow down.")
    if not _ip_limiter.hit(_client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many requests from this address.")

    # 2. Validate site_id & origin. Sites must be registered (no auto-creation).
    site_id = payload.site_id
    if site_id:
        site = db.query(SiteRecord).filter(SiteRecord.site_id == site_id).first()
        if not site:
            raise HTTPException(status_code=404, detail=f"Site ID '{site_id}' is not registered.")
        if not site.is_active:
            raise HTTPException(status_code=403, detail=f"Site '{site_id}' is currently deactivated.")
        _validate_site_origin(site, request)

    # 3. Single idempotent write path. Retry once if a concurrent request won
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
