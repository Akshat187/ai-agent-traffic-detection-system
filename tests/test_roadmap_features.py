"""
Tests for Phase 1-4 Roadmap Fixes & Features:
- Human deliberation explainability gating
- Model persistence & DTW replay pre-filtering
- Site API key & Origin enforcement
- Active mitigation policy (ALLOW / CHALLENGE / BLOCK)
- WebSocket live threat stream
- Analyst feedback endpoint
"""

import time
from fastapi.testclient import TestClient

from apps.api.main import app
from packages.core.features import extract_all_features
from packages.detection.engine import DecisionEngine
from packages.generators.seed_data import generate_synthetic_session

client = TestClient(app)


def test_human_sessions_do_not_leak_agentic_deliberation_signals():
    """Human reading/thinking pauses must not emit agentic planning/adaptation signals."""
    engine = DecisionEngine()
    for subtype in ("organic_mouse", "keyboard_focused"):
        session = generate_synthetic_session(
            label="HUMAN", task="shopping", index=501, subtype=subtype, seed=12345
        )
        feats = extract_all_features(session)
        verdict = engine.evaluate_session(
            session_id=session["session_id"],
            task="shopping",
            session_data=session,
            features=feats,
        )
        joined = " | ".join(verdict["contributing_signals"])
        assert "Goal-directed deliberation pauses" not in joined
        assert "Action adaptation pattern detected" not in joined


def test_site_api_key_origin_and_mitigation_policy():
    """Verify site registration with policy, Origin enforcement, Bearer auth, and BLOCK action."""
    site_resp = client.post(
        "/api/v1/sites",
        json={
            "name": "Policy Test Site",
            "allowed_origins": "https://shop.example.com",
            "risk_threshold": 40,
            "enforcement_mode": "block",
        },
    )
    assert site_resp.status_code == 201
    site_data = site_resp.json()
    site_id = site_data["site_id"]
    api_key = site_data["api_key"]
    assert site_data["enforcement_mode"] == "block"
    assert site_data["risk_threshold"] == 40

    ts = int(time.time() * 1000)
    bot_payload = generate_synthetic_session(label="TRADITIONAL_AUTOMATION", task="shopping", index=ts % 100000)
    bot_payload["site_id"] = site_id

    # 1. Wrong Origin -> 403
    r_bad_origin = client.post(
        "/api/v1/sessions",
        json=bot_payload,
        headers={"Origin": "https://attacker.example.com"},
    )
    assert r_bad_origin.status_code == 403

    # 2. Wrong Bearer token -> 401
    r_bad_key = client.post(
        "/api/v1/sessions",
        json=bot_payload,
        headers={"Authorization": "Bearer ws_live_wrong_key"},
    )
    assert r_bad_key.status_code == 401

    # 3. Valid Bearer token -> 200 with BLOCK action
    r_ok = client.post(
        "/api/v1/sessions",
        json=bot_payload,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert r_ok.status_code == 200
    verdict = r_ok.json()
    assert verdict["action"] == "BLOCK"


def test_websocket_sessions_stream_connects():
    """Verify WS /ws/sessions?site_id=ALL accepts connections cleanly."""
    with client.websocket_connect("/ws/sessions?site_id=ALL") as ws:
        assert ws is not None


def test_analyst_feedback_endpoint():
    """Verify analyst can submit a label override for an existing session."""
    payload = generate_synthetic_session(label="HUMAN", task="forum", index=777123)
    res = client.post("/api/v1/sessions", json=payload)
    assert res.status_code == 200
    sid = res.json()["session_id"]

    fb_res = client.post(
        f"/api/v1/sessions/{sid}/feedback",
        json={"analyst_label": "AGENTIC_AI", "notes": "Verified agentic browser behavior"},
    )
    assert fb_res.status_code == 201
    fb_data = fb_res.json()
    assert fb_data["session_id"] == sid
    assert fb_data["analyst_label"] == "AGENTIC_AI"


def test_mobile_touch_and_a11y_keyboard_not_penalized():
    """Touchscreen and keyboard-only a11y users must not trigger zero-mouse bot penalties."""
    engine = DecisionEngine()

    touch_session = {
        "session_id": "touch_human_001",
        "task": "shopping",
        "duration_ms": 4500.0,
        "browser_signals": {"webdriver": False, "touch_support": True, "pointer_type": "touch"},
        "mouse_events": [],
        "click_events": [{"x": 180, "y": 420, "t": 1200}, {"x": 200, "y": 600, "t": 2800}],
        "keyboard_events": [],
        "scroll_events": [{"t": 800, "scroll_y": 240, "delta_y": 240}],
        "task_actions": [],
    }
    touch_feats = extract_all_features(touch_session)
    touch_verdict = engine.evaluate_session("touch_human_001", "shopping", touch_session, touch_feats)
    assert "DOM_CLICKS_WITHOUT_MOUSE_TRAJECTORY" not in touch_verdict["l1_flags"]
    assert touch_verdict["final_verdict"] == "HUMAN"

    a11y_session = {
        "session_id": "a11y_kb_001",
        "task": "forum",
        "duration_ms": 5000.0,
        "browser_signals": {"webdriver": False, "touch_support": False, "pointer_type": "mouse"},
        "mouse_events": [],
        "click_events": [{"x": 150, "y": 300, "t": 3200}],
        "keyboard_events": [
            {"t": 400, "interval": 160, "hold": 85, "is_paste": False},
            {"t": 720, "interval": 320, "hold": 110, "is_paste": False},
            {"t": 880, "interval": 160, "hold": 75, "is_paste": False},
            {"t": 1310, "interval": 430, "hold": 95, "is_paste": False},
            {"t": 1550, "interval": 240, "hold": 80, "is_paste": False},
        ],
        "scroll_events": [],
        "task_actions": [],
    }
    a11y_feats = extract_all_features(a11y_session)
    a11y_verdict = engine.evaluate_session("a11y_kb_001", "forum", a11y_session, a11y_feats)
    assert "DOM_CLICKS_WITHOUT_MOUSE_TRAJECTORY" not in a11y_verdict["l1_flags"]


def test_prometheus_metrics_endpoint():
    """Verify GET /metrics returns Prometheus text format with HTTP, verdict, and L1-L5 latency metrics."""
    # Trigger at least one classification so verdict & layer metrics are populated
    payload = generate_synthetic_session(label="HUMAN", task="shopping", index=888123)
    client.post("/api/v1/sessions", json=payload)

    res = client.get("/metrics")
    assert res.status_code == 200
    body = res.text
    assert "sentineltrace_http_requests_total" in body
    assert "sentineltrace_classifications_total" in body
    assert "sentineltrace_layer_latency_ms_sum" in body
