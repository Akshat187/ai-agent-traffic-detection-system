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


def test_external_site_agent_detected_without_task_actions():
    """Real-site AI agents (task='general', task_actions=[]) must still expose agency timing features."""
    session = {
        "session_id": "ext_agent_general_001",
        "task": "general",
        "duration_ms": 9500.0,
        "browser_signals": {"webdriver": False, "pointer_type": "mouse"},
        "mouse_events": [],
        "click_events": [
            {"x": 200, "y": 300, "t": 100},
            {"x": 450, "y": 420, "t": 2600},
            {"x": 460, "y": 440, "t": 2780},
            {"x": 700, "y": 510, "t": 5400},
            {"x": 710, "y": 520, "t": 5580},
        ],
        "keyboard_events": [],
        "scroll_events": [],
        "task_actions": [],
    }
    feats = extract_all_features(session)
    assert feats["llm_inference_gap_ratio"] > 0.25
    assert feats["action_burstiness_score"] > 0.30
    engine = DecisionEngine()
    verdict = engine.evaluate_session("ext_agent_general_001", "general", session, feats)
    assert verdict["final_verdict"] == "AGENTIC_AI"


def test_human_prompt_typing_and_fast_typist_not_misclassified():
    """Human typing a prompt (with 2-6s pauses and 26-34ms fast holds) must classify as HUMAN."""
    engine = DecisionEngine()
    prompt_session = generate_synthetic_session(
        label="HUMAN", task="general", index=901, subtype="prompt_typing", seed=4242
    )
    feats = extract_all_features(prompt_session)
    verdict = engine.evaluate_session(prompt_session["session_id"], "general", prompt_session, feats)
    assert verdict["final_verdict"] == "HUMAN"


def test_touchscreen_laptop_does_not_mask_bot():
    """touch_support=True with pointer_type='mouse' must NOT exempt a scripted bot."""
    engine = DecisionEngine()
    bot_on_touch_laptop = generate_synthetic_session(
        label="TRADITIONAL_AUTOMATION", task="general", index=902, subtype="deterministic", seed=777
    )
    bot_on_touch_laptop["browser_signals"]["touch_support"] = True
    bot_on_touch_laptop["browser_signals"]["pointer_type"] = "mouse"
    bot_on_touch_laptop["browser_signals"]["webdriver"] = False
    feats = extract_all_features(bot_on_touch_laptop)
    verdict = engine.evaluate_session("touch_laptop_bot_001", "general", bot_on_touch_laptop, feats)
    assert verdict["final_verdict"] != "HUMAN"


def test_untrusted_and_programmatic_events_flagged():
    """Synthetic isTrusted=false clicks and programmatic inputs must trigger L1 flags."""
    session = {
        "session_id": "untrusted_agent_001",
        "task": "general",
        "duration_ms": 5000.0,
        "browser_signals": {"webdriver": False, "pointer_type": "mouse"},
        "mouse_events": [],
        "click_events": [
            {"x": 200, "y": 300, "t": 100, "is_trusted": False},
            {"x": 450, "y": 420, "t": 2500, "is_trusted": False},
            {"x": 460, "y": 440, "t": 2650, "is_trusted": False},
        ],
        "keyboard_events": [
            {"t": 800, "interval": 0, "hold": 0, "is_paste": False, "is_trusted": False, "is_programmatic": True},
            {"t": 900, "interval": 0, "hold": 0, "is_paste": False, "is_trusted": False, "is_programmatic": True},
        ],
        "scroll_events": [],
        "task_actions": [],
    }
    feats = extract_all_features(session)
    assert feats["untrusted_event_ratio"] == 1.0
    assert feats["programmatic_input_ratio"] == 1.0
    engine = DecisionEngine()
    verdict = engine.evaluate_session("untrusted_agent_001", "general", session, feats)
    assert "UNTRUSTED_SYNTHETIC_EVENTS" in verdict["l1_flags"]
    assert verdict["final_verdict"] != "HUMAN"


def test_verdict_verification_stats_and_model_retrain():
    """Verify Confirm/Correct feedback flow, GET /stats/feedback, and POST /model/retrain."""
    # 1. Confirm a HUMAN verdict via is_correct=True (no analyst_label needed)
    h_payload = generate_synthetic_session(label="HUMAN", task="shopping", index=910001)
    r_h = client.post("/api/v1/sessions", json=h_payload)
    assert r_h.status_code == 200
    h_sid = r_h.json()["session_id"]
    h_pred = r_h.json()["predicted_label"]

    fb1 = client.post(
        f"/api/v1/sessions/{h_sid}/feedback",
        json={"is_correct": True, "notes": "Confirmed via popup"},
    )
    assert fb1.status_code == 201
    fb1_data = fb1.json()
    assert fb1_data["predicted_label"] == h_pred
    assert fb1_data["analyst_label"] == h_pred
    assert fb1_data["is_correct"] is True

    # GET feedback state
    get_fb1 = client.get(f"/api/v1/sessions/{h_sid}/feedback")
    assert get_fb1.status_code == 200
    assert get_fb1.json()["verified"] is True
    assert get_fb1.json()["feedback"]["is_correct"] is True

    # SessionRecord.ground_truth_label and SessionSummary feedback fields should be synced
    detail = client.get(f"/api/v1/sessions/{h_sid}").json()
    assert detail["session"]["ground_truth_label"] == h_pred
    assert detail["session"]["feedback_is_correct"] is True
    assert detail["session"]["feedback_label"] == h_pred

    # 2. Override a second session with is_correct=False
    b_payload = generate_synthetic_session(label="TRADITIONAL_AUTOMATION", task="travel", index=910002)
    r_b = client.post("/api/v1/sessions", json=b_payload)
    b_sid = r_b.json()["session_id"]
    fb2 = client.post(
        f"/api/v1/sessions/{b_sid}/feedback",
        json={"analyst_label": "AGENTIC_AI", "is_correct": False, "notes": "Corrected"},
    )
    assert fb2.status_code == 201
    assert fb2.json()["is_correct"] is False

    # 3. Check GET /api/v1/stats/feedback
    stats_res = client.get("/api/v1/stats/feedback")
    assert stats_res.status_code == 200
    stats = stats_res.json()
    assert stats["total_verified"] >= 2
    assert "accuracy_pct" in stats
    assert "confusion_matrix" in stats

    # 4. Check POST /api/v1/model/retrain
    retrain_res = client.post("/api/v1/model/retrain")
    assert retrain_res.status_code == 200
    retrain_data = retrain_res.json()
    assert "promoted" in retrain_data
    assert "gate_mode" in retrain_data
    assert "candidate_f1" in retrain_data
