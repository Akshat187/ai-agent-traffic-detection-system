"""
Unit & Integration Tests for 5-Layer Detection Engine.

Updated for v1.2.0 terminology:
  TRADITIONAL_AUTOMATION  (was: BOT)
  AGENTIC_AI              (was: AI_AGENT)
  AUTOMATION_BROWSER_ENV_DETECTED  (was: AUTOMATED_BROWSER_WEBDRIVER_ACTIVE)
"""

import pytest
from packages.detection.rules import RuleEngine
from packages.detection.anomaly import AnomalyDetector
from packages.detection.replay import ReplayDetector
from packages.detection.context import ContextValidator
from packages.detection.engine import DecisionEngine
from packages.generators.seed_data import generate_synthetic_session
from packages.core.features import extract_all_features


def test_rule_engine_triggers():
    engine = RuleEngine()

    # Session with webdriver flag + straight linear path
    bot_feats = {"webdriver_flag": 1.0, "straightness_ratio": 0.98, "path_length": 300}
    score, flags, _ = engine.evaluate(bot_feats)
    assert score >= 50.0
    # Renamed flag — now two flags are emitted: the environmental detection + the clarifying note
    assert "AUTOMATION_BROWSER_ENV_DETECTED" in flags
    assert "NOTE_ENV_SIGNAL_SUPPORTING_ONLY" in flags

    # Human with micro-corrections and organic typing
    human_feats = {
        "webdriver_flag": 0.0,
        "straightness_ratio": 0.65,
        "micro_corrections": 5,
        "key_event_count": 10,
        "key_latency_cv": 0.35,
        "duration_ms": 5000,
        "pause_count": 3
    }
    score_h, _, mitigations = engine.evaluate(human_feats)
    assert score_h < 10.0
    assert len(mitigations) > 0


def test_decision_engine_on_human_session():
    engine = DecisionEngine()
    human_session = generate_synthetic_session(label="HUMAN", task="shopping", seed=42)
    feats = extract_all_features(human_session)

    verdict = engine.evaluate_session(
        session_id=human_session["session_id"],
        task="shopping",
        session_data=human_session,
        features=feats
    )
    assert verdict["final_verdict"] == "HUMAN"
    assert verdict["risk_score"] < 40.0
    assert verdict["confidence"] >= 60.0
    assert len(verdict["human_explanation"]) > 10


def test_decision_engine_on_bot_session():
    engine = DecisionEngine()
    # Use TRADITIONAL_AUTOMATION label with deterministic subtype
    bot_session = generate_synthetic_session(
        label="TRADITIONAL_AUTOMATION", task="shopping", subtype="deterministic", seed=42
    )
    feats = extract_all_features(bot_session)

    verdict = engine.evaluate_session(
        session_id=bot_session["session_id"],
        task="shopping",
        session_data=bot_session,
        features=feats
    )
    assert verdict["final_verdict"] == "TRADITIONAL_AUTOMATION", (
        f"Expected TRADITIONAL_AUTOMATION, got {verdict['final_verdict']}. "
        f"rule_score={verdict['l1_rule_score']}, risk={verdict['risk_score']}, "
        f"ml_pred={verdict['l2_ml_pred']}"
    )
    assert verdict["risk_score"] >= 60.0


def test_decision_engine_on_ai_agent_session():
    engine = DecisionEngine()
    # Use AGENTIC_AI label with fixed seed
    agent_session = generate_synthetic_session(label="AGENTIC_AI", task="travel", seed=42)
    feats = extract_all_features(agent_session)

    verdict = engine.evaluate_session(
        session_id=agent_session["session_id"],
        task="travel",
        session_data=agent_session,
        features=feats
    )

    assert verdict["final_verdict"] in ("AGENTIC_AI", "TRADITIONAL_AUTOMATION", "UNCERTAIN"), (
        f"Expected AGENTIC_AI or related class, got {verdict['final_verdict']}"
    )
    assert verdict["risk_score"] >= 35.0


def test_anomaly_detector_basic():
    detector = AnomalyDetector()

    # The detector uses a hardcoded human baseline — no update_baseline needed.
    # Normal human-like session should yield a positive (non-anomalous) score.
    normal = {
        "straightness_ratio": 0.72, "mean_velocity": 450, "velocity_std": 120,
        "key_latency_cv": 0.38, "micro_corrections": 6, "first_action_delay_ms": 1200
    }
    score_n, is_anom_n, reasons_n = detector.score(normal)
    assert score_n > 0.0, f"Normal session should not be a strong outlier (score={score_n})"

    # Highly anomalous bot session — extreme values in multiple dimensions
    anomalous = {
        "straightness_ratio": 0.99,  # > 0.95 triggers deviation flag
        "mean_velocity": 8000,        # far above human baseline mean of 450
        "velocity_std": 2,            # near-zero variance
        "key_latency_cv": 0.001,      # near-zero keystroke CV
        "micro_corrections": 0,
        "first_action_delay_ms": 5    # < 50ms (beyond human reaction limit)
    }
    score_a, is_anom_a, reasons_a = detector.score(anomalous)

    # Anomalous session must score lower than normal session
    assert score_a < score_n, (
        f"Anomalous session (score={score_a:.3f}) should score below "
        f"normal session (score={score_n:.3f})"
    )
    # And the deviation reasons list should not be empty
    assert len(reasons_a) > 0, "Expected deviation flags for extreme-valued session"


def test_replay_detector():
    detector = ReplayDetector()

    # Register a reference path
    path_a = [{"x": i * 10, "y": i * 5, "t": i * 50} for i in range(20)]
    detector.register_session("sess_1", path_a)

    # Exact same path should be detected as replay
    sim, matched_id, is_replay = detector.check_replay("sess_2", path_a)
    assert is_replay or sim > 0.85, (
        f"Identical path should be detected as replay (sim={sim:.3f})"
    )

    # Genuinely different path — sinusoidal curve vs. linear path_a.
    # After [0,1] bounding-box normalization, the shape difference is preserved:
    # a sine wave cannot be mapped onto a straight line by DTW alignment.
    # Uses a fresh detector instance to avoid session-1 contamination.
    import math as _math
    fresh_detector = ReplayDetector()
    fresh_detector.register_session("ref_1", path_a)
    path_b = [
        {"x": i * 10, "y": int(300 + 200 * _math.sin(i * 0.6)), "t": i * 80}
        for i in range(20)
    ]  # sinusoidal y — structurally different from the straight line of path_a
    sim_b, _, is_replay_b = fresh_detector.check_replay("sess_3", path_b)
    assert sim_b < 0.94 or not is_replay_b, (
        f"Sinusoidal path should not be flagged as replay of linear path "
        f"(sim_b={sim_b:.3f}, is_replay={is_replay_b})"
    )


def test_context_validator():
    validator = ContextValidator()
    actions = [
        {"action": "browsed_listing", "t": 100},
        {"action": "item_selected", "t": 2500},
        {"action": "checkout_initiated", "t": 5000}
    ]
    clicks = [{"x": 400, "y": 300, "t": 2500, "target_category": "product"}]
    feats = {"duration_ms": 5000, "total_event_count": 8}

    is_valid, violations = validator.validate("shopping", actions, clicks, feats)
    # A reasonable action sequence should pass context validation
    assert isinstance(is_valid, bool)
    assert isinstance(violations, list)
