"""
Analytics and Platform Overview Statistics — WebSense v1.2.0.

Queries aggregate actor distribution, confidence, and recent session activity.
Uses new actor terminology: TRADITIONAL_AUTOMATION, AGENTIC_AI.
Legacy field names (bot_count, ai_agent_count) are preserved for API compatibility.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from packages.database.db import get_db
from packages.database.models import SessionRecord, SessionFeedback
from packages.database.schemas import OverviewStatsResponse, SessionSummary
from packages.database.repository import build_session_summary, apply_source_filter

router = APIRouter(prefix="/api/v1/stats", tags=["Statistics"])
logger = logging.getLogger("websense.stats")


@router.get("/overview", response_model=OverviewStatsResponse)
def get_overview_stats(
    site_id: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    include_low_signal: bool = Query(False, description="Whether to include low-signal/near-empty sessions in overview stats"),
    db: Session = Depends(get_db)
):
    """Computes aggregated dashboard metrics, actor class distribution, and average confidence, filtering out low-signal phantom sessions by default."""
    low_signal_query = db.query(SessionRecord).filter(SessionRecord.data_quality == "low_signal")
    if site_id and site_id != "ALL":
        low_signal_query = low_signal_query.filter(SessionRecord.site_id == site_id)
    low_signal_query = apply_source_filter(low_signal_query, source)
    low_signal_count = low_signal_query.count()

    base_query = db.query(SessionRecord)
    if site_id and site_id != "ALL":
        base_query = base_query.filter(SessionRecord.site_id == site_id)
    base_query = apply_source_filter(base_query, source)
    if not include_low_signal:
        base_query = base_query.filter(SessionRecord.data_quality != "low_signal")

    total = base_query.count()

    human_count = base_query.filter(SessionRecord.predicted_label == "HUMAN").count()

    # Traditional Automation (new label — also check legacy BOT just in case)
    automation_count = (
        base_query.filter(SessionRecord.predicted_label == "TRADITIONAL_AUTOMATION").count() +
        base_query.filter(SessionRecord.predicted_label == "BOT").count()
    )

    # Agentic AI (new label — also check legacy AI_AGENT just in case)
    agentic_count = (
        base_query.filter(SessionRecord.predicted_label == "AGENTIC_AI").count() +
        base_query.filter(SessionRecord.predicted_label == "AI_AGENT").count()
    )

    uncertain_count = base_query.filter(SessionRecord.predicted_label == "UNCERTAIN").count()

    human_pct       = (human_count / total * 100.0) if total > 0 else 0.0
    automation_pct  = (automation_count / total * 100.0) if total > 0 else 0.0
    agentic_pct     = (agentic_count / total * 100.0) if total > 0 else 0.0
    uncertain_pct   = (uncertain_count / total * 100.0) if total > 0 else 0.0

    avg_conf = base_query.with_entities(func.avg(SessionRecord.confidence)).scalar() or 0.0
    avg_risk = base_query.with_entities(func.avg(SessionRecord.risk_score)).scalar() or 0.0

    # Recent activity (latest 10 sessions)
    recent = base_query.order_by(SessionRecord.created_at.desc()).limit(10).all()
    recent_summaries = [build_session_summary(s) for s in recent]

    from datetime import datetime, timedelta

    # Timeline buckets (real activity over rolling time windows)
    bucket_labels = ["T-5", "T-4", "T-3", "T-2", "T-1", "Now"]
    timeline = [
        {"bucket": lbl, "human": 0, "automation": 0, "agentic": 0, "uncertain": 0}
        for lbl in bucket_labels
    ]

    if total > 0:
        now = datetime.utcnow()
        min_time = base_query.with_entities(func.min(SessionRecord.created_at)).scalar()
        if min_time:
            span_seconds = max((now - min_time).total_seconds(), 300.0)
            step_seconds = span_seconds / 6.0
            start_window = now - timedelta(seconds=span_seconds)

            recent_records = (
                base_query.with_entities(SessionRecord.created_at, SessionRecord.predicted_label)
                .filter(SessionRecord.created_at >= start_window)
                .all()
            )

            for created_at_val, label in recent_records:
                if not created_at_val:
                    idx = 5
                else:
                    offset = (created_at_val - start_window).total_seconds()
                    idx = min(5, max(0, int(offset / step_seconds)))

                if label == "HUMAN":
                    timeline[idx]["human"] += 1
                elif label in ("TRADITIONAL_AUTOMATION", "BOT"):
                    timeline[idx]["automation"] += 1
                elif label in ("AGENTIC_AI", "AI_AGENT"):
                    timeline[idx]["agentic"] += 1
                else:
                    timeline[idx]["uncertain"] += 1

    logger.info(
        "stats_overview total=%d human=%d(%.1f%%) automation=%d(%.1f%%) "
        "agentic=%d(%.1f%%) uncertain=%d(%.1f%%) avg_conf=%.1f avg_risk=%.1f site=%s source=%s",
        total,
        human_count, human_pct,
        automation_count, automation_pct,
        agentic_count, agentic_pct,
        uncertain_count, uncertain_pct,
        avg_conf, avg_risk,
        site_id or "ALL", source or "ALL",
    )

    return OverviewStatsResponse(
        total_sessions=total,
        human_count=human_count,
        human_pct=round(human_pct, 1),
        # Legacy aliases (API backward compatibility)
        bot_count=automation_count,
        bot_pct=round(automation_pct, 1),
        ai_agent_count=agentic_count,
        ai_agent_pct=round(agentic_pct, 1),
        # New preferred fields
        automation_count=automation_count,
        automation_pct=round(automation_pct, 1),
        agentic_count=agentic_count,
        agentic_pct=round(agentic_pct, 1),
        uncertain_count=uncertain_count,
        uncertain_pct=round(uncertain_pct, 1),
        avg_confidence=round(avg_conf, 1),
        avg_risk_score=round(avg_risk, 1),
        recent_activity=recent_summaries,
        detection_timeline=timeline,
        low_signal_count=low_signal_count,
    )


@router.get("/feedback")
def get_feedback_stats(db: Session = Depends(get_db)):
    """
    Computes live real-world accuracy and 3x3 confusion matrix from verified
    user/analyst feedback (latest feedback per unique session_id).
    """
    classes = ["HUMAN", "TRADITIONAL_AUTOMATION", "AGENTIC_AI"]
    rows = db.query(SessionFeedback).order_by(SessionFeedback.id.desc()).all()
    latest_by_session = {}
    for fb in rows:
        if fb.session_id not in latest_by_session:
            latest_by_session[fb.session_id] = fb

    total_verified = len(latest_by_session)
    correct_count = 0
    cm = {pred: {true_cls: 0 for true_cls in classes} for pred in classes}
    class_counts = {c: 0 for c in classes}

    for fb in latest_by_session.values():
        pred = fb.predicted_label
        if not pred:
            sess = db.query(SessionRecord.predicted_label).filter(SessionRecord.session_id == fb.session_id).first()
            pred = sess[0] if sess else "UNCERTAIN"
        true_lbl = fb.analyst_label
        is_ok = fb.is_correct if fb.is_correct is not None else (pred == true_lbl)
        if is_ok:
            correct_count += 1
        if true_lbl in class_counts:
            class_counts[true_lbl] += 1
        if pred in cm and true_lbl in cm[pred]:
            cm[pred][true_lbl] += 1

    accuracy = round((correct_count / total_verified) * 100.0, 2) if total_verified > 0 else None
    return {
        "total_verified": total_verified,
        "correct_count": correct_count,
        "incorrect_count": total_verified - correct_count,
        "accuracy_pct": accuracy,
        "classes": classes,
        "confusion_matrix": cm,
        "verified_class_counts": class_counts,
    }
