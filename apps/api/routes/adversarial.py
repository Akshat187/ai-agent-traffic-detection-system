"""
Adversarial Attack Simulation Lab.

Generates synthetic sessions that embody each attack profile,
then ACTUALLY runs them through the detection engine layer-by-layer.
Returns real engine outputs — not hardcoded strings.
"""

import uuid
from typing import Dict, Any
from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from packages.database.db import get_db
from packages.generators.seed_data import (
    generate_synthetic_session,
    generate_bot_mouse_path,
    generate_human_mouse_path,
)
from packages.core.features import extract_all_features
from apps.api.dependencies import get_detection_engine, DecisionEngine

router = APIRouter(prefix="/api/v1/adversarial", tags=["Adversarial"])

ATTACK_DESCRIPTIONS = {
    "simple_bot": {
        "attack_name":  "Attack 1: Deterministic Scripted Bot",
        "threat_model": (
            "Classic Playwright/Selenium bot. navigator.webdriver=True, perfectly "
            "straight mouse trajectory, uniform 40 ms keystroke intervals."
        ),
    },
    "jitter_evasion": {
        "attack_name":  "Attack 2: Gaussian Jitter Injection",
        "threat_model": (
            "Bot adds Gaussian noise (σ=12 px) to mouse coordinates to mask the "
            "straightness signature. Still webdriver=True."
        ),
    },
    "evasive_bot": {
        "attack_name":  "Attack 3: Fully Evasive Bot",
        "threat_model": (
            "Bot spoofs navigator.webdriver=False, adds large jitter (σ=18 px), "
            "slows interactions, and varies keystroke intervals slightly."
        ),
    },
    "trajectory_replay": {
        "attack_name":  "Attack 4: Human Trajectory Replay",
        "threat_model": (
            "Attacker records a legitimate human session and replays the exact "
            "mouse coordinates. Should be caught by Layer 4 (DTW replay hunter)."
        ),
    },
    "simulated_agent": {
        "attack_name":  "Attack 5: Simulated AI Agent",
        "threat_model": (
            "Autonomous AI agent: deliberate segmented motion, narrow keyboard "
            "interval variance, planning pauses between interactions."
        ),
    },
}


class AdversarialRequest(BaseModel):
    attack_type: str = "simple_bot"
    seed: int = 42


@router.post("/simulate")
def simulate_attack(
    payload: AdversarialRequest,
    db: Session = Depends(get_db),
    engine: DecisionEngine = Depends(get_detection_engine),
) -> Dict[str, Any]:
    """
    Executes a simulated attack scenario through the REAL detection engine.
    Returns actual layer-by-layer results from the defense system.
    """
    ALIAS_MAP = {
        "synthetic_jitter": "jitter_evasion",
        "cross_context": "evasive_bot",
    }
    atk = ALIAS_MAP.get(payload.attack_type, payload.attack_type)
    if atk not in ATTACK_DESCRIPTIONS:
        return {
            "error":        "unknown_attack_type",
            "valid_types":  list(ATTACK_DESCRIPTIONS.keys()) + list(ALIAS_MAP.keys()),
        }

    desc = ATTACK_DESCRIPTIONS[atk]

    # ── Generate session for this attack profile ──────────────────────────────
    import random
    rng = random.Random(payload.seed)

    if atk == "simple_bot":
        session_dict = generate_synthetic_session("BOT", task="shopping", index=999, seed=payload.seed)
        # Ensure deterministic bot characteristics
        session_dict["browser_signals"]["webdriver"] = True
        session_dict["mouse_events"] = generate_bot_mouse_path(
            200, 200, 800, 600, 400, jitter_sigma=0.0, rng=rng
        )

    elif atk == "jitter_evasion":
        session_dict = generate_synthetic_session("BOT", task="travel", index=998, seed=payload.seed)
        session_dict["browser_signals"]["webdriver"] = True
        session_dict["mouse_events"] = generate_bot_mouse_path(
            200, 200, 800, 600, 800, jitter_sigma=12.0, rng=rng
        )

    elif atk == "evasive_bot":
        session_dict = generate_synthetic_session("BOT", task="community", index=997, seed=payload.seed)
        session_dict["browser_signals"]["webdriver"] = False   # spoofed
        session_dict["mouse_events"] = generate_bot_mouse_path(
            200, 200, 800, 600, 2000, jitter_sigma=18.0, rng=rng
        )
        # Slightly more varied keyboard intervals
        cur_t = 100
        kb = []
        for _ in range(12):
            inv = rng.randint(55, 85)   # narrow but not perfectly uniform
            cur_t += inv
            kb.append({"t": cur_t, "interval": inv, "hold": rng.randint(18, 28), "is_paste": False})
        session_dict["keyboard_events"] = kb

    elif atk == "trajectory_replay":
        # Generate a real human session first, then replay it exactly
        original_human = generate_synthetic_session("HUMAN", task="shopping", index=1, seed=42)
        session_dict = {**original_human}
        session_dict["session_id"] = f"adversarial_replay_{uuid.uuid4().hex[:8]}"
        session_dict["visitor_id"]  = "adversarial_attacker_001"
        # Mouse events are IDENTICAL to the human session — that's the attack

    else:  # simulated_agent
        session_dict = generate_synthetic_session("AI_AGENT", task="shopping", index=996, seed=payload.seed)

    session_id = session_dict.get("session_id", f"adversarial_{atk}_{uuid.uuid4().hex[:8]}")
    session_dict["session_id"] = session_id
    task = session_dict.get("task", "shopping")

    # ── Run through real detection engine ────────────────────────────────────
    features = extract_all_features(session_dict)
    verdict  = engine.evaluate_session(
        session_id=session_id,
        task=task,
        session_data=session_dict,
        features=features,
    )

    # ── Format layer-by-layer explanation ────────────────────────────────────
    l1 = f"{'TRIGGERED' if verdict['l1_rule_score'] > 50 else 'PASS'} (Score: {verdict['l1_rule_score']:.0f})"
    l2 = f"{'CAUGHT' if verdict['l2_ml_pred'] in ('BOT','AI_AGENT') else 'PASS'} (Pred: {verdict['l2_ml_pred']}, {verdict['l2_ml_confidence']:.1f}% conf)"
    l3 = f"{'OUTLIER' if verdict['l3_is_anomaly'] else 'PASS'} (Score: {verdict['l3_anomaly_score']:.3f})"
    l4 = f"{'TRIGGERED' if verdict['l4_is_replay'] else 'PASS'} ({verdict['l4_replay_similarity']*100:.1f}% DTW match)"
    l5 = f"{'VIOLATION' if not verdict['l5_context_valid'] else 'PASS'}"

    return {
        "attack_name":     desc["attack_name"],
        "threat_model":    desc["threat_model"],
        "l1_result":       l1,
        "l2_result":       l2,
        "l3_result":       l3,
        "l4_result":       l4,
        "l5_result":       l5,
        "final_verdict":   verdict["final_verdict"],
        "confidence":      verdict["confidence"],
        "risk_score":      verdict["risk_score"],
        "explanation":     verdict["human_explanation"],
        "contributing_signals": verdict["contributing_signals"],
        "counter_signals":      verdict["counter_signals"],
        "model_version":        verdict.get("model_version", "v1.1.0"),
        "data_provenance":      "real_engine_execution",  # NOT hardcoded
        "feature_snapshot": {
            "straightness_ratio": round(features.get("straightness_ratio", 0), 4),
            "key_latency_cv":     round(features.get("key_latency_cv", 0), 4),
            "micro_corrections":  features.get("micro_corrections", 0),
            "webdriver_flag":     features.get("webdriver_flag", 0),
            "mean_velocity":      round(features.get("mean_velocity", 0), 2),
        },
    }
