"""
Repository layer for WebSense.
Centralizes all database write/read logic so route handlers stay thin.

There are exactly two write paths:

  ingest_chunk()   live collectors (SDK / extension / legacy full-blob clients).
                   Idempotent, ownership-checked, seq-ordered. One session row
                   per page visit; every accepted chunk is stored once in
                   telemetry_chunks and features/verdict are rebuilt from ALL
                   chunks of the visit, so telemetry, features and verdict can
                   never disagree.

  create_session() bulk synthetic seeding (one complete session in one call).
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import or_

from packages.database.models import (
    SessionRecord,
    RawTelemetry,
    FeatureRecord,
    DetectionVerdict,
    TelemetryChunk,
    VerdictHistory,
)
from packages.database.schemas import SessionSummary, IngestSessionRequest
from packages.core.features import extract_all_features
from packages.version import MODEL_VERSION, FEATURE_SCHEMA_VERSION

logger = logging.getLogger("websense.ingest")

VALID_TASKS = ("general", "shopping", "travel", "forum", "custom")

# Privacy: the ONLY keyboard fields that may ever be persisted.
_KB_ALLOWED = {"t", "interval", "hold", "is_paste"}
_EVENT_KEYS = ("mouse_events", "keyboard_events", "scroll_events", "click_events", "task_actions")


# ─── Errors ──────────────────────────────────────────────────────────────────

class IngestError(Exception):
    """Raised for client errors in the ingest path. Routes map it to an HTTP status."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ─── Read helpers ────────────────────────────────────────────────────────────

def _fmt_dt(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


def apply_source_filter(query, source: Optional[str]):
    """Filter sessions by data source.

    Accepts:
      - ALL / None / "" → no filter
      - LIVE → non-synthetic / non-demo traffic
      - DEMO → synthetic / demo traffic
      - any exact data_source value (e.g. realtime_sdk, chrome_extension)
    """
    if not source or source == "ALL":
        return query
    key = source.upper()
    if key == "LIVE":
        return query.filter(
            SessionRecord.is_synthetic.isnot(True),
            or_(
                SessionRecord.data_source.is_(None),
                ~SessionRecord.data_source.like("synthetic%"),
            ),
        )
    if key == "DEMO":
        return query.filter(
            or_(
                SessionRecord.is_synthetic.is_(True),
                SessionRecord.data_source.like("synthetic%"),
            )
        )
    return query.filter(SessionRecord.data_source == source)


def build_session_summary(s: SessionRecord) -> SessionSummary:
    explanation = s.verdict.human_explanation if s.verdict else "Analysis pending"
    wf = s.features.webdriver_flag if s.features else False
    return SessionSummary(
        session_id=s.session_id,
        site_id=s.site_id,
        visitor_id=s.visitor_id,
        task=s.task or "general",
        start_time=s.start_time or 0.0,
        duration_ms=s.duration_ms or 0.0,
        data_source=s.data_source or "realtime_sdk",
        ground_truth_label=s.ground_truth_label,
        predicted_label=s.predicted_label or "UNCERTAIN",
        confidence=s.confidence or 0.0,
        risk_score=s.risk_score or 0.0,
        is_synthetic=bool(s.is_synthetic),
        created_at=_fmt_dt(s.created_at) or "",
        webdriver_flag=bool(wf),
        explanation_snippet=explanation or "",
        tab_id=s.tab_id,
        page_path=s.page_path,
        page_title=s.page_title,
        transmission_seq=s.transmission_seq,
        client_context=s.client_context,
        data_quality=getattr(s, "data_quality", "standard") or "standard",
        page_visit_id=s.session_id,
        journey_id=s.journey_id,
        previous_visit_id=s.previous_visit_id,
        page_url=s.page_url,
        custom_task=s.custom_task,
        last_seq=s.last_seq or 0,
        active_duration_ms=s.active_ms,
        updated_at=_fmt_dt(s.updated_at),
    )


def apply_client_context(session_rec: SessionRecord, session_dict: Dict[str, Any]) -> None:
    """Populate tab/page identification fields from client_context payload."""
    ctx = session_dict.get("client_context")
    if not ctx:
        return
    if hasattr(ctx, "model_dump"):
        ctx = ctx.model_dump()
    if not isinstance(ctx, dict):
        return
    session_rec.tab_id = ctx.get("tab_id") or session_rec.tab_id
    session_rec.page_path = (ctx.get("page_path") or "")[:256] or session_rec.page_path
    session_rec.page_title = (ctx.get("page_title") or "")[:256] or session_rec.page_title
    page_url = ctx.get("page_url") or ""
    if ctx.get("page_host"):
        page_url = ctx["page_host"] + (ctx.get("page_path") or "")
    session_rec.page_url = page_url[:512] or session_rec.page_url
    session_rec.client_context = ctx


# ─── Record builders (shared by both write paths) ────────────────────────────

def _feature_fields(features: Dict[str, Any]) -> Dict[str, Any]:
    return dict(
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
        all_features_json=features,
    )


def _verdict_fields(verdict: Dict[str, Any]) -> Dict[str, Any]:
    return dict(
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
        l5_status=verdict.get("l5_status", "not_applicable"),
        final_verdict=verdict["final_verdict"],
        confidence=verdict["confidence"],
        risk_score=verdict["risk_score"],
        contributing_signals=verdict.get("contributing_signals", []),
        counter_signals=verdict.get("counter_signals", []),
        human_explanation=verdict.get("human_explanation", ""),
        model_version=verdict.get("model_version", MODEL_VERSION),
    )


def _build_feature_record(session_id: str, features: Dict[str, Any]) -> FeatureRecord:
    return FeatureRecord(session_id=session_id, **_feature_fields(features))


def _build_verdict_record(session_id: str, verdict: Dict[str, Any]) -> DetectionVerdict:
    return DetectionVerdict(session_id=session_id, **_verdict_fields(verdict))


def _sanitize_keyboard(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Final enforcement point: even if schema validation is bypassed,
    # character content can never reach the DB.
    return [{k: v for k, v in e.items() if k in _KB_ALLOWED} for e in events or []]


def _data_quality(events: Dict[str, List], is_synthetic: bool) -> str:
    n_mouse = len(events.get("mouse_events", []))
    n_key = len(events.get("keyboard_events", []))
    n_scroll = len(events.get("scroll_events", []))
    n_click = len(events.get("click_events", []))
    total = n_mouse + n_key + n_scroll + n_click
    has_signal = n_click > 0 or n_key > 0 or n_scroll >= 2 or n_mouse >= 5
    return "standard" if is_synthetic or (has_signal and total >= 5) else "low_signal"


# ─── Synthetic seeding path ──────────────────────────────────────────────────

def create_session(
    db: DBSession,
    session_dict: Dict[str, Any],
    features: Dict[str, Any],
    verdict: Dict[str, Any],
    data_source: str = "real",
    ground_truth_label: Optional[str] = None,
    is_synthetic: bool = False,
) -> SessionRecord:
    """
    Creates a complete session record (SessionRecord + RawTelemetry + FeatureRecord
    + DetectionVerdict) in one call. Used by synthetic seeding only; live traffic
    goes through ingest_chunk().
    """
    task = (session_dict.get("task") or "general").lower()
    if task == "community":
        task = "forum"
    if task not in VALID_TASKS:
        raise ValueError(f"Unknown task {task!r}; expected one of {VALID_TASKS}")

    now = datetime.utcnow()
    events = {k: session_dict.get(k, []) for k in _EVENT_KEYS}
    session_rec = SessionRecord(
        session_id=session_dict["session_id"],
        visitor_id=session_dict.get("visitor_id"),
        task=task,
        start_time=session_dict.get("start_time"),
        end_time=session_dict.get("end_time"),
        duration_ms=session_dict.get("duration_ms", 0.0),
        active_ms=session_dict.get("active_duration_ms"),
        data_source=data_source,
        ground_truth_label=ground_truth_label,
        is_synthetic=is_synthetic,
        predicted_label=verdict["final_verdict"],
        confidence=verdict["confidence"],
        risk_score=verdict["risk_score"],
        model_version=verdict.get("model_version", MODEL_VERSION),
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        last_seq=1,
        transmission_seq=1,
        created_at=now,
        updated_at=now,
        data_quality=_data_quality(events, is_synthetic),
    )
    apply_client_context(session_rec, session_dict)
    db.add(session_rec)

    db.add(RawTelemetry(
        session_id=session_dict["session_id"],
        mouse_events=events["mouse_events"],
        keyboard_events=_sanitize_keyboard(events["keyboard_events"]),
        scroll_events=events["scroll_events"],
        click_events=events["click_events"],
        browser_signals=session_dict.get("browser_signals", {}),
        task_actions=events["task_actions"],
    ))
    db.add(_build_feature_record(session_dict["session_id"], features))
    db.add(_build_verdict_record(session_dict["session_id"], verdict))
    return session_rec


# ─── Live ingest path ────────────────────────────────────────────────────────

def _insert_ignore(db: DBSession, model, values: Dict[str, Any]) -> bool:
    """
    INSERT ... ON CONFLICT DO NOTHING. Returns True if a row was inserted.
    Works on SQLite and PostgreSQL; other dialects fall back to a savepoint.
    """
    dialect = db.get_bind().dialect.name
    if dialect in ("sqlite", "postgresql"):
        if dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as dialect_insert
        else:
            from sqlalchemy.dialects.postgresql import insert as dialect_insert
        stmt = dialect_insert(model.__table__).values(**values).on_conflict_do_nothing()
        result = db.execute(stmt)
        return (result.rowcount or 0) == 1
    try:
        with db.begin_nested():
            db.add(model(**values))
        return True
    except IntegrityError:
        return False


def _payload_events(payload: IngestSessionRequest) -> Dict[str, List[Dict[str, Any]]]:
    events = {
        "mouse_events": [e.model_dump() for e in payload.mouse_events],
        "keyboard_events": _sanitize_keyboard([e.model_dump() for e in payload.keyboard_events]),
        "scroll_events": [e.model_dump() for e in payload.scroll_events],
        "click_events": [e.model_dump() for e in payload.click_events],
        "task_actions": [e.model_dump() for e in payload.task_actions],
    }
    return events


def _merge_chunks(chunks: List[TelemetryChunk]) -> Tuple[Dict[str, List], Dict[str, Any]]:
    """
    Rebuilds the full event stream of one page visit from its stored chunks.
    Starts from the newest legacy snapshot (if any) and appends every delta
    with a higher seq. Events are sorted by their page-relative time ``t`` so
    late (out-of-order) chunks land in the right place.
    """
    start = 0
    for i, c in enumerate(chunks):
        if c.kind == "snapshot":
            start = i
    merged: Dict[str, List] = {k: [] for k in _EVENT_KEYS}
    browser_signals: Dict[str, Any] = {}
    for c in chunks[start:]:
        if c.kind == "snapshot" and c is not chunks[start]:
            continue
        p = c.payload or {}
        for k in _EVENT_KEYS:
            merged[k].extend(p.get(k) or [])
        if p.get("browser_signals"):
            browser_signals = p["browser_signals"]
    for k in _EVENT_KEYS:
        merged[k].sort(key=lambda e: float(e.get("t", 0) or 0))
    return merged, browser_signals


def _response_from_record(rec: SessionRecord, **flags) -> Dict[str, Any]:
    v = rec.verdict
    return dict(
        session_id=rec.session_id,
        page_visit_id=rec.session_id,
        predicted_label=rec.predicted_label or "UNCERTAIN",
        confidence=rec.confidence or 0.0,
        risk_score=rec.risk_score or 0.0,
        l1_rule_score=(v.l1_rule_score if v else 0.0) or 0.0,
        l2_ml_pred=(v.l2_ml_pred if v else "UNCERTAIN") or "UNCERTAIN",
        l3_is_anomaly=bool(v.l3_is_anomaly) if v else False,
        l4_is_replay=bool(v.l4_is_replay) if v else False,
        l5_context_valid=bool(v.l5_context_valid) if v else True,
        l5_status=(v.l5_status if v else "not_applicable") or "not_applicable",
        contributing_signals=(v.contributing_signals if v else []) or [],
        counter_signals=(v.counter_signals if v else []) or [],
        human_explanation=(v.human_explanation if v else "Analysis pending") or "",
        model_version=rec.model_version or MODEL_VERSION,
        active_duration_ms=rec.active_ms,
        last_seq=rec.last_seq or 0,
        **flags,
    )


def ingest_chunk(
    db: DBSession,
    payload: IngestSessionRequest,
    site_id: Optional[str],
    engine,
    max_chunks_per_session: int = 2000,
) -> Dict[str, Any]:
    """
    Single authoritative write path for live telemetry. Returns a dict matching
    ClassificationResponse. Raises IngestError for client errors. The caller
    commits; on IntegrityError (concurrent first insert on non-SQLite) the caller
    should roll back and retry once.

    Rules:
      * session_id is bound to (site_id, visitor_id) at creation; a mismatch → 409.
      * delta (seq given):  seq already stored → duplicate (no writes)
                            seq < last_seq    → late chunk: stored, features
                                                rebuilt, visit metadata untouched
                            seq > last_seq+1  → gap=true, accepted
      * snapshot (legacy):  seq <= last_seq   → stale, ignored (no writes)
    """
    sid = payload.session_id
    ctx = payload.client_context
    now = datetime.utcnow()

    # 1. Get-or-create the page-visit row atomically.
    _insert_ignore(db, SessionRecord, dict(
        session_id=sid,
        site_id=site_id,
        visitor_id=payload.visitor_id,
        task=payload.task,
        custom_task=payload.custom_task,
        start_time=payload.start_time,
        end_time=payload.end_time,
        duration_ms=payload.duration_ms,
        active_ms=payload.active_duration_ms,
        data_source=payload.data_source or "realtime_sdk",
        ground_truth_label=payload.ground_truth_label,
        is_synthetic=payload.is_synthetic,
        journey_id=payload.journey_id,
        previous_visit_id=payload.previous_visit_id,
        predicted_label="UNCERTAIN",
        confidence=0.0,
        risk_score=0.0,
        model_version=MODEL_VERSION,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        last_seq=0,
        transmission_seq=0,
        data_quality="low_signal",
        created_at=now,
        updated_at=now,
    ))
    rec = (
        db.query(SessionRecord)
        .filter(SessionRecord.session_id == sid)
        .populate_existing()
        .with_for_update()
        .one()
    )

    # 2. Ownership: a session id belongs to one visitor on one site.
    if (rec.site_id or None) != (site_id or None):
        logger.warning("ingest_rejected reason=site_mismatch session_id=%s", sid)
        raise IngestError(409, "session_id belongs to a different site")
    if rec.visitor_id and rec.visitor_id != payload.visitor_id:
        logger.warning("ingest_rejected reason=visitor_mismatch session_id=%s", sid)
        raise IngestError(409, "session_id belongs to a different visitor")
    if not rec.visitor_id and payload.visitor_id:
        rec.visitor_id = payload.visitor_id

    # 3. Resolve seq and classify the chunk.
    last_seq = rec.last_seq or 0
    if payload.is_delta:
        kind, seq = "delta", int(payload.seq)
    else:
        kind = "snapshot"
        seq = int(ctx.transmission_seq) if ctx and ctx.transmission_seq else last_seq + 1
        if seq <= last_seq:
            logger.info("ingest_stale session_id=%s seq=%s last_seq=%s", sid, seq, last_seq)
            return _response_from_record(rec, seq=seq, stale=True)

    exists = db.query(TelemetryChunk.seq).filter(
        TelemetryChunk.session_id == sid, TelemetryChunk.seq == seq
    ).first()
    if exists:
        return _response_from_record(rec, seq=seq, duplicate=True)

    n_chunks = db.query(TelemetryChunk).filter(TelemetryChunk.session_id == sid).count()
    if n_chunks >= max_chunks_per_session:
        raise IngestError(413, "page visit exceeded the maximum number of chunks")

    is_late = seq < last_seq
    gap = kind == "delta" and seq > last_seq + 1

    # 4. Store the chunk exactly once.
    events = _payload_events(payload)
    chunk_payload = dict(events)
    chunk_payload["browser_signals"] = payload.browser_signals.model_dump()
    inserted = _insert_ignore(db, TelemetryChunk, dict(
        session_id=sid,
        seq=seq,
        kind=kind,
        is_final=payload.final,
        event_count=sum(len(v) for v in events.values()),
        received_at=now,
        payload=chunk_payload,
    ))
    if not inserted:  # lost a race with an identical retry
        return _response_from_record(rec, seq=seq, duplicate=True)

    # 5. Visit metadata only moves forward.
    if not is_late:
        rec.last_seq = seq
        rec.transmission_seq = seq
        rec.end_time = payload.end_time
        rec.duration_ms = payload.duration_ms
        if payload.active_duration_ms is not None:
            rec.active_ms = payload.active_duration_ms
        if payload.journey_id and not rec.journey_id:
            rec.journey_id = payload.journey_id
        if payload.previous_visit_id and not rec.previous_visit_id:
            rec.previous_visit_id = payload.previous_visit_id
        apply_client_context(rec, {"client_context": ctx})
    rec.updated_at = now

    # 6. Rebuild the full visit from all chunks and re-evaluate.
    chunks = (
        db.query(TelemetryChunk)
        .filter(TelemetryChunk.session_id == sid)
        .order_by(TelemetryChunk.seq)
        .all()
    )
    merged, browser_signals = _merge_chunks(chunks)
    session_dict: Dict[str, Any] = dict(
        session_id=sid,
        task=rec.task,
        start_time=rec.start_time,
        end_time=rec.end_time,
        duration_ms=rec.duration_ms,
        active_duration_ms=rec.active_ms,
        browser_signals=browser_signals,
        **merged,
    )
    features = extract_all_features(session_dict)
    verdict = engine.evaluate_session(
        session_id=sid,
        task=rec.task,
        session_data=session_dict,
        features=features,
        # Register the trajectory for replay comparison once per visit.
        register_replay=bool(payload.final) or kind == "snapshot",
    )

    # 7. Upsert the three 1:1 child rows so they always reflect the same data.
    telem = rec.telemetry
    if telem is None:
        telem = RawTelemetry(session_id=sid)
        db.add(telem)
    telem.mouse_events = merged["mouse_events"]
    telem.keyboard_events = _sanitize_keyboard(merged["keyboard_events"])
    telem.scroll_events = merged["scroll_events"]
    telem.click_events = merged["click_events"]
    telem.task_actions = merged["task_actions"]
    telem.browser_signals = browser_signals

    feat = rec.features
    if feat is None:
        db.add(_build_feature_record(sid, features))
    else:
        for k, v in _feature_fields(features).items():
            setattr(feat, k, v)

    det = rec.verdict
    if det is None:
        db.add(_build_verdict_record(sid, verdict))
    else:
        for k, v in _verdict_fields(verdict).items():
            setattr(det, k, v)

    rec.predicted_label = verdict["final_verdict"]
    rec.confidence = verdict["confidence"]
    rec.risk_score = verdict["risk_score"]
    rec.model_version = verdict.get("model_version", MODEL_VERSION)
    rec.feature_schema_version = FEATURE_SCHEMA_VERSION
    rec.data_quality = _data_quality(merged, payload.is_synthetic)

    db.add(VerdictHistory(
        session_id=sid,
        seq=seq,
        label=verdict["final_verdict"],
        confidence=verdict["confidence"],
        risk_score=verdict["risk_score"],
        event_count=sum(len(v) for v in merged.values()),
        evidence={
            "contributing": verdict.get("contributing_signals", []),
            "counter": verdict.get("counter_signals", []),
            "l5_status": verdict.get("l5_status"),
        },
        model_version=verdict.get("model_version", MODEL_VERSION),
        created_at=now,
    ))

    logger.info(
        "ingest_ok session_id=%s seq=%s kind=%s last_seq=%s late=%s gap=%s final=%s chunks=%s label=%s",
        sid, seq, kind, rec.last_seq, is_late, gap, payload.final, len(chunks), verdict["final_verdict"],
    )

    return dict(
        session_id=sid,
        page_visit_id=sid,
        predicted_label=verdict["final_verdict"],
        confidence=verdict["confidence"],
        risk_score=verdict["risk_score"],
        l1_rule_score=verdict["l1_rule_score"],
        l2_ml_pred=verdict["l2_ml_pred"],
        l3_is_anomaly=verdict["l3_is_anomaly"],
        l4_is_replay=verdict["l4_is_replay"],
        l5_context_valid=verdict["l5_context_valid"],
        l5_status=verdict.get("l5_status", "not_applicable"),
        contributing_signals=verdict.get("contributing_signals", []),
        counter_signals=verdict.get("counter_signals", []),
        human_explanation=verdict.get("human_explanation", ""),
        model_version=verdict.get("model_version", MODEL_VERSION),
        active_duration_ms=rec.active_ms,
        seq=seq,
        last_seq=rec.last_seq,
        gap=bool(gap),
    )
