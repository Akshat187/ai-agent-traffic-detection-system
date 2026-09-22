"""
Repository layer for WebSense.
Centralizes all database write/read logic so route handlers stay thin.
This eliminates the duplication between sessions.py and seed.py.
"""

from typing import Optional, Dict, Any
from sqlalchemy.orm import Session as DBSession

from packages.database.models import (
    SessionRecord,
    RawTelemetry,
    FeatureRecord,
    DetectionVerdict,
)
from packages.database.schemas import SessionSummary
from apps.api.config import settings


def build_session_summary(s: SessionRecord) -> SessionSummary:
    explanation = s.verdict.human_explanation if s.verdict else "Analysis pending"
    wf = s.features.webdriver_flag if s.features else False
    return SessionSummary(
        session_id=s.session_id,
        site_id=s.site_id,
        visitor_id=s.visitor_id,
        task=s.task,
        start_time=s.start_time or 0.0,
        duration_ms=s.duration_ms,
        data_source=s.data_source or "realtime_sdk",
        ground_truth_label=s.ground_truth_label,
        predicted_label=s.predicted_label,
        confidence=s.confidence,
        risk_score=s.risk_score,
        is_synthetic=s.is_synthetic,
        created_at=s.created_at.strftime("%Y-%m-%d %H:%M:%S") if s.created_at else "",
        webdriver_flag=wf,
        explanation_snippet=explanation,
        tab_id=s.tab_id,
        page_path=s.page_path,
        page_title=s.page_title,
        transmission_seq=s.transmission_seq,
        client_context=s.client_context,
        data_quality=getattr(s, "data_quality", "standard") or "standard",
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
    session_rec.tab_id = ctx.get("tab_id")
    session_rec.page_path = ctx.get("page_path")
    session_rec.page_title = ctx.get("page_title")
    session_rec.transmission_seq = ctx.get("transmission_seq", 1)
    session_rec.client_context = ctx


def _build_feature_record(session_id: str, features: Dict[str, Any]) -> FeatureRecord:
    return FeatureRecord(
        session_id=session_id,
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


def _build_verdict_record(session_id: str, verdict: Dict[str, Any]) -> DetectionVerdict:
    return DetectionVerdict(
        session_id=session_id,
        l1_rule_score=verdict["l1_rule_score"],
        l1_flags=verdict["l1_flags"],
        l2_ml_pred=verdict["l2_ml_pred"],
        l2_ml_confidence=verdict["l2_ml_confidence"],
        l2_ml_probabilities=verdict["l2_ml_probabilities"],
        l3_anomaly_score=verdict["l3_anomaly_score"],
        l3_is_anomaly=verdict["l3_is_anomaly"],
        l4_replay_similarity=verdict["l4_replay_similarity"],
        l4_matched_session_id=verdict["l4_matched_session_id"],
        l4_is_replay=verdict["l4_is_replay"],
        l5_context_valid=verdict["l5_context_valid"],
        l5_context_violations=verdict["l5_context_violations"],
        final_verdict=verdict["final_verdict"],
        confidence=verdict["confidence"],
        risk_score=verdict["risk_score"],
        contributing_signals=verdict["contributing_signals"],
        counter_signals=verdict["counter_signals"],
        human_explanation=verdict["human_explanation"],
        model_version=verdict.get("model_version", settings.MODEL_VERSION),
    )


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
    Creates a complete session record (SessionRecord + RawTelemetry + FeatureRecord + DetectionVerdict).
    This is the single authoritative write path for any new session.
    """
    # Normalize task value
    task = session_dict.get("task", "shopping")
    if task not in settings.VALID_TASKS:
        task = "shopping"

    session_rec = SessionRecord(
        session_id=session_dict["session_id"],
        visitor_id=session_dict.get("visitor_id"),
        task=task,
        start_time=session_dict.get("start_time"),
        end_time=session_dict.get("end_time"),
        duration_ms=session_dict.get("duration_ms", 0.0),
        data_source=data_source,
        ground_truth_label=ground_truth_label,
        is_synthetic=is_synthetic,
        predicted_label=verdict["final_verdict"],
        confidence=verdict["confidence"],
        risk_score=verdict["risk_score"],
        model_version=verdict.get("model_version", settings.MODEL_VERSION),
        feature_schema_version=settings.FEATURE_SCHEMA_VERSION,
    )
    apply_client_context(session_rec, session_dict)
    db.add(session_rec)

    raw = RawTelemetry(
        session_id=session_dict["session_id"],
        mouse_events=session_dict.get("mouse_events", []),
        keyboard_events=session_dict.get("keyboard_events", []),
        scroll_events=session_dict.get("scroll_events", []),
        click_events=session_dict.get("click_events", []),
        browser_signals=session_dict.get("browser_signals", {}),
        task_actions=session_dict.get("task_actions", []),
    )
    db.add(raw)
    db.add(_build_feature_record(session_dict["session_id"], features))
    db.add(_build_verdict_record(session_dict["session_id"], verdict))

    return session_rec


def update_session_verdict(
    db: DBSession,
    existing: SessionRecord,
    session_dict: Dict[str, Any],
    verdict: Dict[str, Any],
) -> None:
    """Updates verdict fields on an existing session (e.g. on duplicate ingest)."""
    existing.end_time = session_dict.get("end_time", existing.end_time)
    existing.duration_ms = session_dict.get("duration_ms", existing.duration_ms)
    existing.predicted_label = verdict["final_verdict"]
    existing.confidence = verdict["confidence"]
    existing.risk_score = verdict["risk_score"]
    existing.model_version = verdict.get("model_version", settings.MODEL_VERSION)
    apply_client_context(existing, session_dict)

