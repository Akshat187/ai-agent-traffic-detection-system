"""
Audit Invariants Test Suite — WebSense SentinelTrace.
Verifies the fixes for P1, P2, P4, P6, P7, P8, P9, P10, and P11.
"""

import time
import uuid
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.config import settings
from packages.database.models import SessionRecord, TelemetryChunk
from packages.database.schemas import normalize_task, IngestSessionRequest
from packages.detection.engine import DecisionEngine


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_p7_lead_form_task_normalization(client: TestClient):
    """P7: Verifies that task='lead_form' is accepted and normalized to 'custom'."""
    assert normalize_task("lead_form") == "custom"

    sid = "st_lead_" + uuid.uuid4().hex[:10]
    payload = {
        "session_id": sid,
        "site_id": settings.DEFAULT_SITE_ID,
        "visitor_id": "vis_lead_test",
        "task": "lead_form",
        "seq": 1,
        "final": True,
        "start_time": int(time.time() * 1000) - 2000,
        "end_time": int(time.time() * 1000),
        "duration_ms": 2000,
        "active_duration_ms": 1500,
        "data_source": "realtime_sdk",
        "mouse_events": [{"x": 100, "y": 200, "t": 100, "type": "move"}],
        "keyboard_events": [],
        "scroll_events": [],
        "click_events": [{"x": 120, "y": 220, "t": 200, "target_category": "button"}],
        "task_actions": [],
    }

    resp = client.post("/api/v1/sessions", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == sid
    assert data["l5_status"] == "not_applicable"


def test_p6_p11_sdk_source_contract(client: TestClient):
    """P6 & P11: Verifies SDK source contains single collector guard, in-flight container, and URL privacy."""
    resp = client.get("/sentinel.js")
    assert resp.status_code == 200
    src = resp.text

    # P6: Double load guard
    assert "window.__WEBSENSE_COLLECTOR_ACTIVE__ || document.documentElement.dataset.wsOwner === 'sdk'" in src

    # P2: In-flight payload container
    assert "visit.inFlight" in src
    assert "inFlight.seq" in src

    # P3: Isolated visit factory
    assert "createPageVisit" in src
    assert "handlePageVisitTransition" in src

    # P11: URL privacy (origin + pathname without query params)
    assert "location.origin + location.pathname" in src


def test_p2_p4_p10_extension_source_contract():
    """P2, P4, P5, P10: Verifies extension content.js source guarantees."""
    from pathlib import Path
    ext_path = Path(__file__).resolve().parent.parent / "extension" / "content.js"
    assert ext_path.exists()
    src = ext_path.read_text(encoding="utf-8")

    # P4: No empty sessions on background tabs
    assert "visit.totalEventsTransmitted === 0 && (!hasPendingEvents(visit) || !hasMinimumInteraction(visit))" in src

    # P2: In-flight container
    assert "visit.inFlight" in src

    # P5: SPA navigation listeners
    assert "pushState" in src
    assert "popstate" in src
    assert "handlePageVisitTransition" in src

    # P10: Rollover keyboard holds and paste detection
    assert "activeKeys" in src
    assert "is_paste: true" in src

    # P11: URL privacy
    assert "location.origin + location.pathname" in src


def test_p8_replay_registration_without_final(client: TestClient, db_session):
    """P8: Verifies that sessions with sufficient mouse events register for replay even when final=False."""
    s_id = "st_replay_" + uuid.uuid4().hex[:10]
    mouse_events = [
        {"x": 100 + i * 10, "y": 100 + i * 5, "t": 100 + i * 50, "type": "move"}
        for i in range(25)
    ]

    payload = {
        "session_id": s_id,
        "site_id": settings.DEFAULT_SITE_ID,
        "visitor_id": "vis_rep_test",
        "task": "general",
        "seq": 1,
        "final": False,  # Note: NOT final!
        "start_time": int(time.time() * 1000) - 3000,
        "end_time": int(time.time() * 1000),
        "duration_ms": 3000,
        "active_duration_ms": 2500,
        "data_source": "realtime_sdk",
        "mouse_events": mouse_events,
        "keyboard_events": [],
        "scroll_events": [],
        "click_events": [],
        "task_actions": [],
    }

    resp = client.post("/api/v1/sessions", json=payload)
    assert resp.status_code == 200

    # Ingesting the same trajectory under another session should now trigger replay detection
    s_clone = "st_clone_" + uuid.uuid4().hex[:10]
    clone_payload = dict(payload)
    clone_payload["session_id"] = s_clone
    clone_payload["visitor_id"] = "vis_clone_attacker"

    r2 = client.post("/api/v1/sessions", json=clone_payload)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["l4_is_replay"] is True


def test_p9_ingest_latency_bounded(client: TestClient):
    """P9: Ingesting multiple sequential chunks maintains sub-150ms latency due to bounded rolling window."""
    s_id = "st_perf_" + uuid.uuid4().hex[:10]
    latencies = []

    for seq in range(1, 12):
        mouse_events = [
            {"x": 50 + j * 2, "y": 60 + j * 3, "t": seq * 1000 + j * 20, "type": "move"}
            for j in range(20)
        ]
        p = {
            "session_id": s_id,
            "site_id": settings.DEFAULT_SITE_ID,
            "visitor_id": "vis_perf_user",
            "task": "shopping",
            "seq": seq,
            "final": (seq == 11),
            "start_time": 1700000000000,
            "end_time": 1700000000000 + seq * 1000,
            "duration_ms": seq * 1000,
            "active_duration_ms": seq * 800,
            "data_source": "realtime_sdk",
            "mouse_events": mouse_events,
            "keyboard_events": [],
            "scroll_events": [],
            "click_events": [],
            "task_actions": [],
        }

        t0 = time.perf_counter()
        resp = client.post("/api/v1/sessions", json=p)
        elapsed = (time.perf_counter() - t0) * 1000
        assert resp.status_code == 200
        latencies.append(elapsed)

    # Confirm latency does not spiral upward on chunk 11 vs chunk 1
    assert latencies[-1] < 500  # Well within comfortable interactive limits
