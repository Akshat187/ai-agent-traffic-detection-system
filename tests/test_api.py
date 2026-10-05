"""
Integration and API Endpoint Tests using FastAPI TestClient.

Phase 1 fixes:
  - Updated brand assertions (Meridian, not AeroTech/SkyHorizon/CyberSec Pulse)
  - Updated predicted_label valid set (current terminology)
  - Experiments test now seeds data before running experiments
  - Experiments test now expects 6 experiments (current count)
  - Adversarial test updated with current valid attack types
"""

import time
import pytest
from fastapi.testclient import TestClient
from apps.api.main import app
from packages.generators.seed_data import generate_synthetic_session

client = TestClient(app)


def test_health_endpoints():
    res1 = client.get("/healthz")
    assert res1.status_code == 200
    assert res1.json()["status"] == "healthy"

    res2 = client.get("/readyz")
    assert res2.status_code == 200
    assert res2.json()["status"] == "ready"


def test_overview_stats_endpoint():
    res = client.get("/api/v1/stats/overview")
    assert res.status_code == 200
    data = res.json()
    assert "total_sessions" in data
    assert "human_pct" in data
    assert "bot_pct" in data
    assert "ai_agent_pct" in data


def test_session_ingestion_and_detail_flow():
    # Ingest new session
    payload = generate_synthetic_session(label="HUMAN", task="shopping", index=99)
    res = client.post("/api/v1/sessions", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["session_id"] == payload["session_id"]
    # Current label set — legacy labels are no longer emitted by the engine
    valid_labels = {"HUMAN", "TRADITIONAL_AUTOMATION", "AGENTIC_AI", "UNCERTAIN"}
    assert data["predicted_label"] in valid_labels, (
        f"Unexpected label: {data['predicted_label']}"
    )
    assert "confidence" in data
    assert "risk_score" in data

    # Retrieve session details
    detail_res = client.get(f"/api/v1/sessions/{payload['session_id']}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["session"]["session_id"] == payload["session_id"]
    assert "features" in detail
    assert "verdict" in detail
    assert "telemetry" in detail


def _seed_experiment_data(n_per_class: int = 8):
    """
    Seeds at least n_per_class sessions for each of the 3 classes across 3 tasks.
    Uses unique timestamps so sessions don't collide with other test runs.
    """
    ts = int(time.time())
    classes = ["TRADITIONAL_AUTOMATION", "AGENTIC_AI", "HUMAN"]
    tasks = ["shopping", "travel", "forum"]
    idx = 0
    for cls in classes:
        for task in tasks:
            for i in range(n_per_class // 3 + 1):
                payload = generate_synthetic_session(
                    label=cls, task=task, index=ts * 1000 + idx
                )
                # Ensure unique session_id across test runs
                payload["session_id"] = f"test_exp_{cls.lower()}_{task}_{ts}_{idx:04d}"
                client.post("/api/v1/sessions", json=payload)
                idx += 1


def test_experiments_benchmark_endpoint():
    # Seed data FIRST — the experiments endpoint returns 422 on empty DB
    _seed_experiment_data(n_per_class=9)

    res = client.post("/api/v1/experiments/run")
    assert res.status_code == 200, (
        f"Expected 200, got {res.status_code}. Body: {res.text[:500]}"
    )
    data = res.json()
    assert data["status"] == "success"
    # Currently runs 6 experiments (browser_only, mouse_only, keyboard_only,
    # scroll_click_only, behavioral_all, combined)
    assert len(data["experiments"]) == 6, (
        f"Expected 6 experiments, got {len(data['experiments'])}"
    )
    assert "feature_importance" in data
    assert "confusion_matrix" in data
    assert data["data_provenance"] == "real_computed"


def test_adversarial_simulator_endpoint():
    # Valid attack types as of current adversarial.py
    attacks = ["simple_bot", "jitter_evasion", "evasive_bot",
               "trajectory_replay", "simulated_agent"]
    for atk in attacks:
        res = client.post("/api/v1/adversarial/simulate", json={"attack_type": atk})
        assert res.status_code == 200, f"Attack {atk!r} returned {res.status_code}"
        data = res.json()
        assert "attack_name" in data, f"Missing attack_name for {atk!r}"
        assert "final_verdict" in data, f"Missing final_verdict for {atk!r}"
        assert "explanation" in data, f"Missing explanation for {atk!r}"


def test_web_page_rendering():
    res_dash = client.get("/dashboard")
    assert res_dash.status_code == 200
    # Dashboard title should mention the platform name
    assert "WebSense" in res_dash.text or "SentinelTrace" in res_dash.text

    res_shop = client.get("/visitor/shop")
    assert res_shop.status_code == 200
    # Unified brand — shop is now "Meridian"
    assert "Meridian" in res_shop.text, (
        "Shop page should contain the Meridian brand. "
        f"Got: {res_shop.text[:200]}"
    )

    res_travel = client.get("/visitor/travel")
    assert res_travel.status_code == 200
    # Unified brand — travel is now "Meridian Travel"
    assert "Meridian" in res_travel.text, (
        "Travel page should contain the Meridian brand."
    )

    res_forum = client.get("/visitor/forum")
    assert res_forum.status_code == 200
    # Unified brand — forum is now "Meridian Community"
    assert "Meridian" in res_forum.text, (
        "Forum page should contain the Meridian brand."
    )


def test_utf8_encoding_integrity():
    """Validates that pages and endpoints return correct UTF-8 glyphs without mojibake."""
    # 1. Check shop page for currency, em dashes, and emojis
    res_shop = client.get("/visitor/shop")
    assert res_shop.status_code == 200
    html_shop = res_shop.text
    assert "₹" in html_shop, "Currency ₹ symbol should render cleanly"
    assert "₹2,199" in html_shop or "₹2,499" in html_shop, "Sample currency price should render cleanly"
    assert "Â" not in html_shop, "Double-encoded currency symbol found"
    assert "â€”" not in html_shop, "Double-encoded em dash found"
    assert "—" in html_shop, "Em dash should render cleanly"
    assert "© 2026" in html_shop or "2026" in html_shop

    # 2. Check travel page for flight prices and arrows
    res_travel = client.get("/visitor/travel")
    assert res_travel.status_code == 200
    html_travel = res_travel.text
    assert "₹" in html_travel, "Currency ₹ symbol should render cleanly in travel page"
    assert "Â" not in html_travel
    assert "â†’" not in html_travel

    # 3. Check forum page for clean bullet dots and emojis
    res_forum = client.get("/visitor/forum")
    assert res_forum.status_code == 200
    html_forum = res_forum.text
    assert "Â·" not in html_forum
    assert "ðŸ" not in html_forum


def test_data_quality_low_signal_gating():
    """Validates that low-signal/near-empty sessions are flagged as low_signal and excluded from default stats."""
    import uuid
    # 1. Ingest low-signal session (only 2 mouse points, 0 keys, 0 scroll, 0 clicks)
    low_sid = f"test_low_sig_{uuid.uuid4().hex[:8]}"
    low_payload = {
        "session_id": low_sid,
        "site_id": "site_meridian_prod",
        "task": "shopping",
        "start_time": 1700000000.0,
        "end_time": 1700000005.0,
        "duration_ms": 5000.0,
        "is_synthetic": False,
        "data_source": "chrome_extension",
        "browser_signals": {"webdriver": False},
        "mouse_events": [
            {"x": 100, "y": 100, "t": 100, "type": "move"},
            {"x": 101, "y": 100, "t": 150, "type": "move"}
        ],
        "keyboard_events": [],
        "scroll_events": [],
        "click_events": [],
        "task_actions": []
    }
    ingest_res = client.post("/api/v1/sessions", json=low_payload)
    assert ingest_res.status_code == 200
    assert ingest_res.json()["predicted_label"] == "UNCERTAIN"

    # 2. Check session detail: data_quality must be 'low_signal' and verdict 'UNCERTAIN'
    detail_res = client.get(f"/api/v1/sessions/{low_sid}")
    assert detail_res.status_code == 200
    session_data = detail_res.json()["session"]
    assert session_data["data_quality"] == "low_signal", (
        f"Expected data_quality='low_signal', got {session_data['data_quality']}"
    )
    assert session_data["predicted_label"] == "UNCERTAIN"

    # 3. Overview stats default excludes low_signal sessions
    stats_clean = client.get("/api/v1/stats/overview").json()
    stats_all = client.get("/api/v1/stats/overview?include_low_signal=true").json()
    assert stats_all["total_sessions"] > stats_clean["total_sessions"]
    assert stats_clean["low_signal_count"] > 0


def test_session_delta_updates_raw_telemetry_and_features():
    """Verifies that subsequent delta chunks synchronously update raw telemetry and feature child records."""
    import uuid
    sid = f"test_delta_sync_{uuid.uuid4().hex[:8]}"

    chunk1 = {
        "session_id": sid,
        "site_id": "site_meridian_prod",
        "task": "shopping",
        "seq": 1,
        "is_delta": True,
        "start_time": 1700000000.0,
        "end_time": 1700000002.0,
        "duration_ms": 2000.0,
        "is_synthetic": False,
        "data_source": "realtime_sdk",
        "browser_signals": {"webdriver": False},
        "mouse_events": [
            {"x": 100 + i * 10, "y": 100 + i * 5, "t": 100 * i, "type": "move"}
            for i in range(6)
        ],
        "keyboard_events": [],
        "scroll_events": [],
        "click_events": [],
        "task_actions": []
    }
    r1 = client.post("/api/v1/sessions", json=chunk1)
    assert r1.status_code == 200

    detail1 = client.get(f"/api/v1/sessions/{sid}").json()
    assert len(detail1["telemetry"]["mouse_events"]) == 6

    chunk2 = {
        "session_id": sid,
        "site_id": "site_meridian_prod",
        "task": "shopping",
        "seq": 2,
        "is_delta": True,
        "final": True,
        "start_time": 1700000000.0,
        "end_time": 1700000005.0,
        "duration_ms": 5000.0,
        "is_synthetic": False,
        "data_source": "realtime_sdk",
        "browser_signals": {"webdriver": False},
        "mouse_events": [
            {"x": 200 + i * 10, "y": 200 + i * 5, "t": 1000 + 100 * i, "type": "move"}
            for i in range(6)
        ],
        "keyboard_events": [],
        "scroll_events": [],
        "click_events": [{"x": 260, "y": 230, "t": 1800, "target_category": "button"}],
        "task_actions": []
    }
    r2 = client.post("/api/v1/sessions", json=chunk2)
    assert r2.status_code == 200

    detail2 = client.get(f"/api/v1/sessions/{sid}").json()
    # Telemetry must contain all 12 events accumulated across both chunks
    assert len(detail2["telemetry"]["mouse_events"]) == 12
    assert len(detail2["telemetry"]["click_events"]) == 1
    # Features must be populated and non-empty
    assert detail2["features"].get("straightness_ratio") is not None
    assert detail2["session"]["last_seq"] == 2



