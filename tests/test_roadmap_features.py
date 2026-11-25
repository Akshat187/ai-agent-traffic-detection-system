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
