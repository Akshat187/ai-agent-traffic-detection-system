"""
WebSense SentinelTrace — Session Architecture Integration Tests (S1–S18).

Validates:
- 1 session = 1 page visit architecture (session_id == page_visit_id)
- Journey grouping and previous visit linking
- Monotonic delta chunks merging, idempotency, out-of-order handling
- Timeline and History endpoints
- Ownership verification (409 Conflict)
- Rate limiting per session (429)
- Task normalization, validation, and L5 policy status
- Active duration round-trip
"""

import time
import uuid
from typing import Optional
import pytest
from fastapi.testclient import TestClient

from packages.database.models import SessionRecord, TelemetryChunk, VerdictHistory
from apps.api.config import settings


def make_payload(
    session_id: str,
    seq: int = 1,
    final: bool = False,
    site_id: str = settings.DEFAULT_SITE_ID,
    visitor_id: str = "vis_arch_test",
    journey_id: str = "jny_arch_test",
    previous_visit_id: Optional[str] = None,
    task: str = "general",
    mouse_count: int = 5,
    active_duration_ms: int = 2500,
    duration_ms: int = 3000,
    client_context: Optional[dict] = None,
) -> dict:
    """Generates a valid schema-compliant telemetry payload."""
    now_ms = int(time.time() * 1000)
    mouse_events = [
        {"x": 100 + i * 5, "y": 150 + i * 4, "t": 100 + i * 30, "type": "move"}
        for i in range(mouse_count)
    ]
    clicks = [
        {"x": 120, "y": 160, "t": 350, "target_category": "button"}
    ] if mouse_count > 0 else []

    context = client_context or {
        "tab_id": "tab_arch_123",
        "page_path": "/visitor/shop",
        "page_title": "Shop — Meridian",
        "page_url": "http://localhost:8000/visitor/shop",
        "referrer_path": "",
        "visibility_state": "visible",
        "transmission_seq": seq,
        "sdk_version": "sentinel-2.0",
    }

    return {
        "session_id": session_id,
        "page_visit_id": session_id,
        "journey_id": journey_id,
        "previous_visit_id": previous_visit_id,
        "site_id": site_id,
        "visitor_id": visitor_id,
        "seq": seq,
        "final": final,
        "task": task,
        "start_time": now_ms - duration_ms,
        "end_time": now_ms,
        "duration_ms": duration_ms,
        "active_duration_ms": active_duration_ms,
        "data_source": "sentinel_sdk",
        "browser_signals": {
            "webdriver": False,
            "screen_width": 1920,
            "screen_height": 1080,
            "viewport_width": 1280,
            "viewport_height": 800,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TestSuite/1.0",
        },
        "client_context": context,
        "mouse_events": mouse_events,
        "keyboard_events": [],
        "scroll_events": [],
        "click_events": clicks,
        "task_actions": [],
    }


# S1: Single page visit with interactions generates exactly 1 session record
def test_s1_single_page_visit_single_session(client: TestClient, db_session):
    s_id = "st_" + uuid.uuid4().hex[:12]
    payload = make_payload(session_id=s_id, seq=1, final=True)

    resp = client.post("/api/v1/sessions", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == s_id
    assert "predicted_label" in data
    assert "risk_score" in data

    # Verify exactly 1 database record exists
    records = db_session.query(SessionRecord).filter_by(session_id=s_id).all()
    assert len(records) == 1
    record = records[0]
    assert record.session_id == s_id
    assert record.page_visit_id == s_id
    assert record.last_seq == 1
    assert record.is_final is True


# S2: Delta chunks merging, last_seq updating, and history accumulation
def test_s2_delta_chunks_merging_and_timeline(client: TestClient, db_session):
    s_id = "st_" + uuid.uuid4().hex[:12]

    # Chunk 1 (10 mouse events)
    p1 = make_payload(session_id=s_id, seq=1, final=False, mouse_count=10, active_duration_ms=1000)
    r1 = client.post("/api/v1/sessions", json=p1)
    assert r1.status_code == 200

    # Chunk 2 (8 mouse events)
    p2 = make_payload(session_id=s_id, seq=2, final=False, mouse_count=8, active_duration_ms=2500)
    r2 = client.post("/api/v1/sessions", json=p2)
    assert r2.status_code == 200
    assert r2.json().get("duplicate") is False

    # Chunk 3 (4 mouse events, final)
    p3 = make_payload(session_id=s_id, seq=3, final=True, mouse_count=4, active_duration_ms=4200)
    r3 = client.post("/api/v1/sessions", json=p3)
    assert r3.status_code == 200

    record = db_session.query(SessionRecord).filter_by(session_id=s_id).first()
    assert record is not None
    assert record.last_seq == 3
    assert record.active_ms == 4200
    # Cumulative merged mouse events: 10 + 8 + 4 = 22
    events = record.telemetry.mouse_events if record.telemetry and isinstance(record.telemetry.mouse_events, list) else []
    assert len(events) == 22

    # Verify verdict history contains all 3 chunk classifications
    history = db_session.query(VerdictHistory).filter_by(session_id=s_id).order_by(VerdictHistory.seq.asc()).all()
    assert len(history) == 3
    assert [h.seq for h in history] == [1, 2, 3]


# S3: Final flag finalizes session and persists verdict
def test_s3_final_flag_finalizes_session(client: TestClient, db_session):
    s_id = "st_" + uuid.uuid4().hex[:12]

    p1 = make_payload(session_id=s_id, seq=1, final=False)
    client.post("/api/v1/sessions", json=p1)

    rec = db_session.query(SessionRecord).filter_by(session_id=s_id).first()
    assert rec.is_final is False

    p2 = make_payload(session_id=s_id, seq=2, final=True)
    client.post("/api/v1/sessions", json=p2)

    db_session.refresh(rec)
    assert rec.is_final is True


# S4: Reload/navigation links journey and previous page visit
def test_s4_reload_navigation_links_journey_and_prev_visit(client: TestClient, db_session):
    jny_id = "jny_" + uuid.uuid4().hex[:10]
    vis_id = "vis_" + uuid.uuid4().hex[:10]
    s1_id = "st_" + uuid.uuid4().hex[:12]
    s2_id = "st_" + uuid.uuid4().hex[:12]

    # Visit 1
    p1 = make_payload(
        session_id=s1_id,
        visitor_id=vis_id,
        journey_id=jny_id,
        previous_visit_id=None,
        seq=1,
        final=True,
    )
    r1 = client.post("/api/v1/sessions", json=p1)
    assert r1.status_code == 200

    # Visit 2 (Navigated to new page in same tab)
    p2 = make_payload(
        session_id=s2_id,
        visitor_id=vis_id,
        journey_id=jny_id,
        previous_visit_id=s1_id,
        seq=1,
        final=True,
    )
    r2 = client.post("/api/v1/sessions", json=p2)
    assert r2.status_code == 200

    rec1 = db_session.query(SessionRecord).filter_by(session_id=s1_id).first()
    rec2 = db_session.query(SessionRecord).filter_by(session_id=s2_id).first()
    assert rec1.journey_id == jny_id
    assert rec2.journey_id == jny_id
    assert rec1.previous_visit_id is None
    assert rec2.previous_visit_id == s1_id


# S5: Timeline route returns sequence of verdicts
def test_s5_session_verdict_timeline_endpoint(client: TestClient):
    s_id = "st_" + uuid.uuid4().hex[:12]
    client.post("/api/v1/sessions", json=make_payload(session_id=s_id, seq=1, final=False))
    client.post("/api/v1/sessions", json=make_payload(session_id=s_id, seq=2, final=True))

    resp = client.get(f"/api/v1/sessions/{s_id}/timeline")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == s_id
    assert len(data["timeline"]) == 2
    assert data["timeline"][0]["seq"] == 1
    assert data["timeline"][1]["seq"] == 2
    assert "predicted_label" in data["timeline"][0]
    assert "confidence" in data["timeline"][0]


# S6: History route returns full session summary
def test_s6_session_history_endpoint(client: TestClient):
    s_id = "st_" + uuid.uuid4().hex[:12]
    client.post("/api/v1/sessions", json=make_payload(session_id=s_id, seq=1, final=True, active_duration_ms=3500))

    resp = client.get(f"/api/v1/sessions/{s_id}/history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session"]["session_id"] == s_id
    assert data["session"]["active_duration_ms"] == 3500
    assert data["session"]["site_id"] == settings.DEFAULT_SITE_ID
    assert "predicted_label" in data["session"]
    assert "risk_score" in data["session"]
    assert "features" in data
    assert "verdict" in data


# S7: Out-of-order chunks arrival
def test_s7_out_of_order_chunks_handling(client: TestClient, db_session):
    s_id = "st_" + uuid.uuid4().hex[:12]

    # seq 2 arrives first
    p2 = make_payload(session_id=s_id, seq=2, final=False, mouse_count=6)
    r2 = client.post("/api/v1/sessions", json=p2)
    assert r2.status_code == 200

    rec = db_session.query(SessionRecord).filter_by(session_id=s_id).first()
    assert rec.last_seq == 2

    # seq 1 arrives second
    p1 = make_payload(session_id=s_id, seq=1, final=False, mouse_count=8)
    r1 = client.post("/api/v1/sessions", json=p1)
    assert r1.status_code == 200

    db_session.refresh(rec)
    # last_seq must not rewind to 1
    assert rec.last_seq == 2
    # Both chunks stored in TelemetryChunk
    chunks = db_session.query(TelemetryChunk).filter_by(session_id=s_id).all()
    assert len(chunks) == 2
    # Events merged
    events = rec.telemetry.mouse_events if rec.telemetry and isinstance(rec.telemetry.mouse_events, list) else []
    assert len(events) == 14


# S8: Idempotent retransmission
def test_s8_idempotent_retransmission(client: TestClient, db_session):
    s_id = "st_" + uuid.uuid4().hex[:12]
    payload = make_payload(session_id=s_id, seq=1, final=False, mouse_count=10)

    # First transmission
    r1 = client.post("/api/v1/sessions", json=payload)
    assert r1.status_code == 200
    assert r1.json().get("duplicate") is False

    # Exact duplicate retransmission
    r2 = client.post("/api/v1/sessions", json=payload)
    assert r2.status_code == 200
    assert r2.json().get("duplicate") is True

    rec = db_session.query(SessionRecord).filter_by(session_id=s_id).first()
    events = rec.telemetry.mouse_events if rec.telemetry and isinstance(rec.telemetry.mouse_events, list) else []
    # Count must remain 10, not 20
    assert len(events) == 10


# S9: Zero interaction / empty event buffers handled without crash
def test_s9_zero_interaction_empty_events_handling(client: TestClient):
    s_id = "st_" + uuid.uuid4().hex[:12]
    payload = make_payload(session_id=s_id, seq=1, final=True, mouse_count=0)

    resp = client.post("/api/v1/sessions", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == s_id
    assert data["predicted_label"] in ("UNCERTAIN", "HUMAN")


# S10: Multiple visits under same journey_id queryable
def test_s10_journey_grouped_visits_query(client: TestClient, db_session):
    jny_id = "jny_" + uuid.uuid4().hex[:10]
    vis_id = "vis_" + uuid.uuid4().hex[:10]

    for i in range(3):
        s_id = f"st_{jny_id[:6]}_{i}"
        p = make_payload(session_id=s_id, visitor_id=vis_id, journey_id=jny_id, seq=1, final=True)
        r = client.post("/api/v1/sessions", json=p)
        assert r.status_code == 200

    visits = db_session.query(SessionRecord).filter_by(journey_id=jny_id).all()
    assert len(visits) == 3


# S11: Late arriving chunk does not rewind last_seq
def test_s11_late_arriving_chunk_does_not_rewind_last_seq(client: TestClient, db_session):
    s_id = "st_" + uuid.uuid4().hex[:12]
    client.post("/api/v1/sessions", json=make_payload(session_id=s_id, seq=1))
    client.post("/api/v1/sessions", json=make_payload(session_id=s_id, seq=4))

    rec = db_session.query(SessionRecord).filter_by(session_id=s_id).first()
    assert rec.last_seq == 4

    # Late arrival of seq 3
    client.post("/api/v1/sessions", json=make_payload(session_id=s_id, seq=3))

    db_session.refresh(rec)
    assert rec.last_seq == 4


# S12: Gap in sequence handled gracefully
def test_s12_gap_in_sequence_handled_gracefully(client: TestClient):
    s_id = "st_" + uuid.uuid4().hex[:12]
    r1 = client.post("/api/v1/sessions", json=make_payload(session_id=s_id, seq=1))
    assert r1.status_code == 200

    # Skip seq 2, send seq 3
    r3 = client.post("/api/v1/sessions", json=make_payload(session_id=s_id, seq=3))
    assert r3.status_code == 200
    assert r3.json()["session_id"] == s_id
    assert r3.json()["gap"] is True


# S13: Mismatched visitor_id or site_id returns 409 Conflict
def test_s13_mismatched_visitor_or_site_returns_409(client: TestClient):
    s_id = "st_" + uuid.uuid4().hex[:12]
    vis_alice = "vis_alice_" + uuid.uuid4().hex[:6]
    vis_mallory = "vis_mallory_" + uuid.uuid4().hex[:6]

    # Alice initializes session
    p1 = make_payload(session_id=s_id, visitor_id=vis_alice, site_id=settings.DEFAULT_SITE_ID, seq=1)
    r1 = client.post("/api/v1/sessions", json=p1)
    assert r1.status_code == 200

    # Mallory attempts to inject chunk into Alice's session -> 409
    p2 = make_payload(session_id=s_id, visitor_id=vis_mallory, site_id=settings.DEFAULT_SITE_ID, seq=2)
    r2 = client.post("/api/v1/sessions", json=p2)
    assert r2.status_code == 409
    assert "visitor" in r2.json()["detail"].lower()

    # Different site attempts to claim session -> 409
    p3 = make_payload(session_id=s_id, visitor_id=vis_alice, site_id=settings.EXTENSION_SITE_ID, seq=3)
    r3 = client.post("/api/v1/sessions", json=p3)
    assert r3.status_code == 409


# S14: Unregistered site rejected with 400 or 404
def test_s14_unregistered_site_rejected_with_400_or_404(client: TestClient):
    s_id = "st_" + uuid.uuid4().hex[:12]
    p = make_payload(session_id=s_id, site_id="site_non_existent_corp")
    resp = client.post("/api/v1/sessions", json=p)
    assert resp.status_code in (400, 404)
    assert "not registered" in resp.json()["detail"]


# S15: Chrome extension site ingest succeeds
def test_s15_chrome_extension_site_ingest(client: TestClient):
    s_id = "ext_st_" + uuid.uuid4().hex[:12]
    p = make_payload(session_id=s_id, site_id=settings.EXTENSION_SITE_ID, task="general")
    resp = client.post("/api/v1/sessions", json=p)
    assert resp.status_code == 200
    assert resp.json()["session_id"] == s_id


# S16: Rate limiter throttles excessive burst
def test_s16_rate_limiter_throttles_burst(client: TestClient):
    s_id = "st_burst_" + uuid.uuid4().hex[:10]
    limit = settings.INGEST_MAX_CHUNKS_PER_SESSION_PER_MIN

    throttled = False
    for seq in range(1, limit + 10):
        p = make_payload(session_id=s_id, seq=seq, mouse_count=1)
        resp = client.post("/api/v1/sessions", json=p)
        if resp.status_code == 429:
            throttled = True
            assert "Too many" in resp.json()["detail"]
            break

    assert throttled, f"Expected 429 after exceeding {limit} requests for session"


# S17: Task validation and L5 policy status
def test_s17_task_validation_and_l5_policy(client: TestClient):
    # Valid workflow task ("flight_booking" -> normalized to "travel")
    s1 = "st_" + uuid.uuid4().hex[:12]
    r1 = client.post("/api/v1/sessions", json=make_payload(session_id=s1, task="flight_booking"))
    assert r1.status_code == 200
    assert r1.json()["l5_status"] in ("valid", "violated", "not_applicable")

    # Valid canonical workflow task ("travel")
    s2 = "st_" + uuid.uuid4().hex[:12]
    r2 = client.post("/api/v1/sessions", json=make_payload(session_id=s2, task="travel"))
    assert r2.status_code == 200
    assert r2.json()["l5_status"] in ("valid", "violated", "not_applicable")

    # Valid non-workflow task ("general") gets "not_applicable"
    s3 = "st_" + uuid.uuid4().hex[:12]
    r3 = client.post("/api/v1/sessions", json=make_payload(session_id=s3, task="general"))
    assert r3.status_code == 200
    assert r3.json()["l5_status"] == "not_applicable"

    # Invalid task gets 422 Unprocessable Entity
    s4 = "st_" + uuid.uuid4().hex[:12]
    r4 = client.post("/api/v1/sessions", json=make_payload(session_id=s4, task="invalid_arbitrary_task"))
    assert r4.status_code == 422


# S18: Active duration ms roundtrip
def test_s18_active_duration_ms_roundtrip(client: TestClient, db_session):
    s_id = "st_" + uuid.uuid4().hex[:12]
    active_ms = 48750
    p = make_payload(session_id=s_id, active_duration_ms=active_ms, seq=1, final=True)

    resp = client.post("/api/v1/sessions", json=p)
    assert resp.status_code == 200
    assert resp.json()["active_duration_ms"] == active_ms

    # Check DB
    rec = db_session.query(SessionRecord).filter_by(session_id=s_id).first()
    assert rec.active_ms == active_ms

    # Check history endpoint
    h_resp = client.get(f"/api/v1/sessions/{s_id}/history")
    assert h_resp.status_code == 200
    assert h_resp.json()["session"]["active_duration_ms"] == active_ms
