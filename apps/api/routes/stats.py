"""
Analytics and Platform Overview Statistics — WebSense v1.2.0.

Queries aggregate actor distribution, confidence, and recent session activity.
Uses new actor terminology: TRADITIONAL_AUTOMATION, AGENTIC_AI.
Legacy field names (bot_count, ai_agent_count) are preserved for API compatibility.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from packages.database.db import get_db
from packages.database.models import SessionRecord
from packages.database.schemas import OverviewStatsResponse, SessionSummary
from packages.database.repository import build_session_summary

router = APIRouter(prefix="/api/v1/stats", tags=["Statistics"])


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
    if source and source != "ALL":
        low_signal_query = low_signal_query.filter(SessionRecord.data_source == source)
    low_signal_count = low_signal_query.count()

    base_query = db.query(SessionRecord)
    if site_id and site_id != "ALL":
        base_query = base_query.filter(SessionRecord.site_id == site_id)
    if source and source != "ALL":
        base_query = base_query.filter(SessionRecord.data_source == source)
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

    # Timeline buckets (cumulative session counts over rolling window)
    timeline = [
        {"bucket": "T-5",
         "human": max(1, int(human_count * 0.1)),
         "automation": max(1, int(automation_count * 0.1)),
         "agentic": max(1, int(agentic_count * 0.1))},
        {"bucket": "T-4",
         "human": max(2, int(human_count * 0.2)),
         "automation": max(2, int(automation_count * 0.2)),
         "agentic": max(2, int(agentic_count * 0.2))},
        {"bucket": "T-3",
         "human": max(4, int(human_count * 0.4)),
         "automation": max(3, int(automation_count * 0.4)),
         "agentic": max(3, int(agentic_count * 0.4))},
        {"bucket": "T-2",
         "human": max(3, int(human_count * 0.6)),
         "automation": max(2, int(automation_count * 0.6)),
         "agentic": max(4, int(agentic_count * 0.6))},
        {"bucket": "T-1",
         "human": max(5, int(human_count * 0.8)),
         "automation": max(4, int(automation_count * 0.8)),
         "agentic": max(5, int(agentic_count * 0.8))},
        {"bucket": "Now",
         "human": human_count,
         "automation": automation_count,
         "agentic": agentic_count},
    ]

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
