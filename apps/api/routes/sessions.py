"""
Session Ingestion and Telemetry Retrieval REST Endpoints.
"""

from typing import List, Optional
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from packages.database.db import get_db
from packages.database.models import SessionRecord, RawTelemetry, FeatureRecord, DetectionVerdict, SiteRecord
from packages.database.schemas import (
    IngestSessionRequest,
    ClassificationResponse,
    SessionSummary,
    SessionDetailResponse
)
from packages.core.features import extract_all_features
from apps.api.dependencies import get_detection_engine, DecisionEngine

import logging
import time
import secrets
from collections import defaultdict
from apps.api.config import settings
from packages.database.repository import apply_client_context, build_session_summary

router = APIRouter(prefix="/api/v1/sessions", tags=["Sessions"])
logger = logging.getLogger("websense.ingest")

# In-memory sliding window rate limiter: IP -> list of timestamps
_RATE_LIMIT_WINDOW_SEC = 60.0
_MAX_REQUESTS_PER_WINDOW = 60
_request_history = defaultdict(list)


def _check_rate_limit(client_ip: str):
    """Enforces 60 requests per minute rate limit per IP."""
    now = time.time()
    cutoff = now - _RATE_LIMIT_WINDOW_SEC
    # Filter expired timestamps
    _request_history[client_ip] = [t for t in _request_history[client_ip] if t > cutoff]
    if len(_request_history[client_ip]) >= _MAX_REQUESTS_PER_WINDOW:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Maximum 60 session submissions per minute allowed."
        )
    _request_history[client_ip].append(now)


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
    Ingests raw behavioral telemetry, validates site origin and site_id,
    extracts high-resolution kinematic features, executes the 5-layer detection engine,
    and persists the session verdict.
    """
    # 1. Apply rate limiting per client IP
    if request and request.client:
        client_ip = request.client.host
        _check_rate_limit(client_ip)

    # 2. Validate site_id & origin if site_id is specified
    site_id = payload.site_id
    if site_id:
        site = db.query(SiteRecord).filter(SiteRecord.site_id == site_id).first()
        if not site:
            if site_id.startswith("site_chrome_ext_") or site_id in ("site_meridian_prod", "meridian_demo"):
                site = SiteRecord(
                    site_id=site_id,
                    name=f"Extension: {site_id.replace('site_chrome_ext_', '')}",
                    allowed_origins="*",
                    api_key=f"ws_ext_{secrets.token_hex(8)}",
                    is_active=True
                )
                db.add(site)
                db.commit()
            else:
                raise HTTPException(status_code=404, detail=f"Site ID '{site_id}' is not registered.")
        elif not site.is_active:
            raise HTTPException(status_code=403, detail=f"Site '{site_id}' is currently deactivated.")
        else:
            _validate_site_origin(site, request)

    session_dict = payload.model_dump()
    ctx = payload.client_context
    logger.info(
        "session_ingest session_id=%s tab_id=%s page_path=%s page_title=%s visitor_id=%s transmission_seq=%s task=%s",
        payload.session_id,
        ctx.tab_id if ctx else "-",
        ctx.page_path if ctx else "-",
        ctx.page_title if ctx else "-",
        payload.visitor_id or "-",
        ctx.transmission_seq if ctx else "-",
        payload.task,
    )
    features = extract_all_features(session_dict)
    
    verdict = engine.evaluate_session(
        session_id=payload.session_id,
        task=payload.task,
        session_data=session_dict,
        features=features
    )

    # Check if session already exists
    existing = db.query(SessionRecord).filter(SessionRecord.session_id == payload.session_id).first()
    if existing:
        # Update existing session record
        existing.end_time = payload.end_time
        existing.duration_ms = payload.duration_ms
        existing.site_id = site_id or existing.site_id
        existing.data_source = payload.data_source or existing.data_source
        existing.predicted_label = verdict["final_verdict"]
        existing.confidence = verdict["confidence"]
        existing.risk_score = verdict["risk_score"]
        existing.model_version = settings.MODEL_VERSION
        existing.feature_schema_version = settings.FEATURE_SCHEMA_VERSION
        tot_ev = len(payload.mouse_events) + len(payload.keyboard_events) + len(payload.scroll_events) + len(payload.click_events)
        has_sig = (len(payload.click_events) > 0 or len(payload.keyboard_events) > 0 or len(payload.scroll_events) >= 2 or len(payload.mouse_events) >= 5 or payload.is_synthetic)
        existing.data_quality = "standard" if (has_sig and tot_ev >= 5) or payload.is_synthetic else "low_signal"
        apply_client_context(existing, session_dict)

        # CRITICAL: Also update the DetectionVerdict so it stays in sync with SessionRecord.
        # Without this, the badge reads the updated SessionRecord while the explanation text
        # reads the stale original DetectionVerdict — causing opposite verdicts on the same row.
        existing_verdict = db.query(DetectionVerdict).filter(
            DetectionVerdict.session_id == payload.session_id
        ).first()
        if existing_verdict:
            existing_verdict.l1_rule_score = verdict["l1_rule_score"]
            existing_verdict.l1_flags = verdict.get("l1_flags", [])
            existing_verdict.l2_ml_pred = verdict["l2_ml_pred"]
            existing_verdict.l2_ml_confidence = verdict.get("l2_ml_confidence", 0.0)
            existing_verdict.l2_ml_probabilities = verdict.get("l2_ml_probabilities", {})
            existing_verdict.l3_anomaly_score = verdict.get("l3_anomaly_score", 0.0)
            existing_verdict.l3_is_anomaly = verdict["l3_is_anomaly"]
            existing_verdict.l4_replay_similarity = verdict.get("l4_replay_similarity", 0.0)
            existing_verdict.l4_matched_session_id = verdict.get("l4_matched_session_id")
            existing_verdict.l4_is_replay = verdict["l4_is_replay"]
            existing_verdict.l5_context_valid = verdict["l5_context_valid"]
            existing_verdict.l5_context_violations = verdict.get("l5_context_violations", [])
            existing_verdict.final_verdict = verdict["final_verdict"]
            existing_verdict.confidence = verdict["confidence"]
            existing_verdict.risk_score = verdict["risk_score"]
            existing_verdict.contributing_signals = verdict.get("contributing_signals", [])
            existing_verdict.counter_signals = verdict.get("counter_signals", [])
            existing_verdict.human_explanation = verdict.get("human_explanation", "")
            existing_verdict.model_version = settings.MODEL_VERSION

            # Integrity assertion: log loudly if label in explanation doesn't match badge label.
            # This guards against regressions in the verdict→explanation pipeline.
            explanation_text = existing_verdict.human_explanation or ""
            badge_label = existing.predicted_label
            label_map = {
                "HUMAN": "human",
                "TRADITIONAL_AUTOMATION": "traditional automation",
                "AGENTIC_AI": "agentic ai",
                "UNCERTAIN": "uncertain",
            }
            expected_phrase = label_map.get(badge_label, "").lower()
            if expected_phrase and expected_phrase not in explanation_text.lower():
                import logging as _logging
                _logging.getLogger("websense.integrity").error(
                    "[VERDICT MISMATCH DETECTED] session=%s badge=%s explanation_snippet=%s",
                    payload.session_id, badge_label, explanation_text[:120]
                )
        else:
            existing_verdict = DetectionVerdict(
                session_id=payload.session_id,
                site_id=site_id,
                l1_rule_score=verdict["l1_rule_score"],
                l1_flags=verdict.get("l1_flags", []),
                l2_ml_pred=verdict["l2_ml_pred"],
                l2_ml_confidence=verdict.get("l2_ml_confidence", 0.0),
                l2_ml_probabilities=verdict.get("l2_ml_probabilities", {}),
                l3_anomaly_score=verdict.get("l3_anomaly_score", 0.0),
                l3_is_anomaly=verdict["l3_is_anomaly"],
                l4_replay_similarity=verdict.get("l4_replay_similarity", 0.0),
                l4_matched_session_id=verdict.get("l4_matched_session_id"),
                l4_is_replay=verdict["l4_is_replay"],
                l5_context_valid=verdict["l5_context_valid"],
                l5_context_violations=verdict.get("l5_context_violations", []),
                final_verdict=verdict["final_verdict"],
                confidence=verdict["confidence"],
                risk_score=verdict["risk_score"],
                contributing_signals=verdict.get("contributing_signals", []),
                counter_signals=verdict.get("counter_signals", []),
                human_explanation=verdict.get("human_explanation", ""),
                model_version=settings.MODEL_VERSION
            )
            db.add(existing_verdict)
    else:
        # Create new session record
        session_rec = SessionRecord(
            session_id=payload.session_id,
            site_id=site_id,
            visitor_id=payload.visitor_id,
            task=payload.task,
            start_time=payload.start_time,
            end_time=payload.end_time,
            duration_ms=payload.duration_ms,
            ground_truth_label=payload.ground_truth_label,
            is_synthetic=payload.is_synthetic,
            data_source=payload.data_source or "realtime_sdk",
            predicted_label=verdict["final_verdict"],
            confidence=verdict["confidence"],
            risk_score=verdict["risk_score"],
            model_version=settings.MODEL_VERSION,
            feature_schema_version=settings.FEATURE_SCHEMA_VERSION,
            data_quality="standard" if (
                payload.is_synthetic or (
                    (len(payload.click_events) > 0 or len(payload.keyboard_events) > 0 or len(payload.scroll_events) >= 2 or len(payload.mouse_events) >= 5) and
                    (len(payload.mouse_events) + len(payload.keyboard_events) + len(payload.scroll_events) + len(payload.click_events)) >= 5
                )
            ) else "low_signal",
        )
        apply_client_context(session_rec, session_dict)
        db.add(session_rec)


        # Store raw telemetry
        # Privacy: keyboard events are explicitly filtered to timing-only fields
        # before storage. This is the final enforcement point — even if upstream
        # schema validation is bypassed, character content cannot reach the DB.
        _KB_ALLOWED = {"t", "interval", "hold", "is_paste"}
        safe_keyboard_events = [
            {k: v for k, v in evt.items() if k in _KB_ALLOWED}
            for evt in session_dict.get("keyboard_events", [])
        ]

        raw_telemetry = RawTelemetry(
            session_id=payload.session_id,
            mouse_events=session_dict.get("mouse_events", []),
            keyboard_events=safe_keyboard_events,
            scroll_events=session_dict.get("scroll_events", []),
            click_events=session_dict.get("click_events", []),
            browser_signals=session_dict.get("browser_signals", {}),
            task_actions=session_dict.get("task_actions", [])
        )
        db.add(raw_telemetry)


        # Store features
        feat_rec = FeatureRecord(
            session_id=payload.session_id,
            mouse_mean_velocity=features.get("mean_velocity", 0.0),
            mouse_velocity_std=features.get("velocity_std", 0.0),
            mouse_acceleration_std=features.get("acceleration_std", 0.0),
            mouse_jerk_mean=features.get("jerk_mean", 0.0),
            mouse_straightness_ratio=features.get("straightness_ratio", 1.0),
            mouse_micro_corrections=features.get("micro_corrections", 0),
            mouse_direction_changes=features.get("direction_changes", 0),
            mouse_pause_ratio=features.get("pause_time_ratio", 0.0),
            mouse_low_speed_ratio=features.get("low_speed_ratio", 0.0),
            key_mean_latency=features.get("key_mean_latency", 0.0),
            key_latency_std=features.get("key_latency_std", 0.0),
            key_latency_cv=features.get("key_latency_cv", 0.0),
            key_mean_hold_time=features.get("key_mean_hold_time", 0.0),
            key_paste_count=features.get("key_paste_count", 0),
            scroll_velocity_mean=features.get("scroll_velocity_mean", 0.0),
            scroll_velocity_std=features.get("scroll_velocity_std", 0.0),
            scroll_discrete_jump_ratio=features.get("scroll_discrete_jump_ratio", 0.0),
            interaction_first_action_delay=features.get("first_action_delay_ms", 0.0),
            interaction_click_interval_std=features.get("click_interval_std", 0.0),
            interaction_density=features.get("interaction_density", 0.0),
            webdriver_flag=bool(features.get("webdriver_flag", 0.0)),
            all_features_json=features
        )
        db.add(feat_rec)

        # Store verdict
        det_verdict = DetectionVerdict(
            session_id=payload.session_id,
            l1_rule_score=verdict["l1_rule_score"],
            l1_flags=verdict.get("l1_flags", []),
            l2_ml_pred=verdict["l2_ml_pred"],
            l2_ml_confidence=verdict.get("l2_ml_confidence", 0.0),
            l2_ml_probabilities=verdict.get("l2_ml_probabilities", {}),
            l3_anomaly_score=verdict.get("l3_anomaly_score", 0.0),
            l3_is_anomaly=verdict["l3_is_anomaly"],
            l4_replay_similarity=verdict.get("l4_replay_similarity", 0.0),
            l4_matched_session_id=verdict.get("l4_matched_session_id"),
            l4_is_replay=verdict["l4_is_replay"],
            l5_context_valid=verdict["l5_context_valid"],
            l5_context_violations=verdict.get("l5_context_violations", []),
            final_verdict=verdict["final_verdict"],
            confidence=verdict["confidence"],
            risk_score=verdict["risk_score"],
            contributing_signals=verdict.get("contributing_signals", []),
            counter_signals=verdict.get("counter_signals", []),
            human_explanation=verdict.get("human_explanation", ""),
            model_version=settings.MODEL_VERSION
        )
        db.add(det_verdict)

    db.commit()

    return ClassificationResponse(
        session_id=payload.session_id,
        predicted_label=verdict["final_verdict"],
        confidence=verdict["confidence"],
        risk_score=verdict["risk_score"],
        l1_rule_score=verdict["l1_rule_score"],
        l2_ml_pred=verdict["l2_ml_pred"],
        l3_is_anomaly=verdict["l3_is_anomaly"],
        l4_is_replay=verdict["l4_is_replay"],
        l5_context_valid=verdict["l5_context_valid"],
        contributing_signals=verdict.get("contributing_signals", []),
        counter_signals=verdict.get("counter_signals", []),
        human_explanation=verdict.get("human_explanation", ""),
        model_version=settings.MODEL_VERSION
    )


@router.get("", response_model=List[SessionSummary])
def list_sessions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    label: Optional[str] = Query(None),
    site_id: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Lists recent session summaries with optional site_id and label filters."""
    query = db.query(SessionRecord).order_by(SessionRecord.created_at.desc())
    if label and label != "ALL":
        query = query.filter(SessionRecord.predicted_label == label)
    if site_id and site_id != "ALL":
        query = query.filter(SessionRecord.site_id == site_id)
    if source and source != "ALL":
        query = query.filter(SessionRecord.data_source == source)
    
    sessions = query.offset(offset).limit(limit).all()
    return [build_session_summary(s) for s in sessions]


@router.get("/{session_id}", response_model=SessionDetailResponse)
def get_session_detail(session_id: str, db: Session = Depends(get_db)):
    """Fetches full session details including 2D trajectory coordinates, features, and layer breakdown."""
    session = db.query(SessionRecord).filter(SessionRecord.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

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
