"""
Unified Actor Inference Engine — WebSense v1.2.0

Harmonizes behavioral, environmental, and contextual signals across all 5 layers
into a single explainable actor classification with confidence and risk scores.

Actor Classes:
  HUMAN                  — organic human browser interaction
  TRADITIONAL_AUTOMATION — deterministic scripted automation (e.g. Playwright, Selenium)
  AGENTIC_AI             — goal-driven adaptive browser agent (e.g. LLM-driven web agents)
  UNCERTAIN              — insufficient evidence for confident classification

Classification Disclaimer:
  Output is an evidence-based behavioral estimate. It does not directly identify
  the software or model controlling the browser. Sophisticated agents may exhibit
  behavior indistinguishable from human interaction.

Signal Hierarchy:
  Behavioral/Contextual signals (primary weight: 0.75)
  Environmental signals (supporting weight: 0.25)
"""

from typing import Dict, Any, List, Optional
from packages.detection.rules import RuleEngine
from packages.detection.ml_classifier import BehavioralClassifier
from packages.detection.anomaly import AnomalyDetector
from packages.detection.replay import ReplayDetector
from packages.detection.context import ContextValidator
from packages.version import MODEL_VERSION

# Tasks that have Layer-5 workflow rules. Every other task is "not_applicable".
WORKFLOW_TASKS = ("shopping", "travel", "forum")


class DecisionEngine:
    """Master Actor Inference Engine for WebSense.

    Synthesizes evidence from 5 detection layers to classify web sessions into:
      HUMAN | TRADITIONAL_AUTOMATION | AGENTIC_AI | UNCERTAIN

    The final verdict is an evidence-based behavioral estimate, not a direct
    identification of the underlying software or AI model.
    """

    def __init__(self):
        self.rules = RuleEngine()
        self.ml = BehavioralClassifier()
        self.anomaly = AnomalyDetector()
        self.replay = ReplayDetector(similarity_threshold=0.96)
        self.context = ContextValidator()
        self._bootstrap_ml()

    def _bootstrap_ml(self):
        """Pre-trains and calibrates behavioral classifier. Prioritizes persistent benchmark traces from disk."""
        try:
            import json
            from pathlib import Path
            from packages.core.features import extract_all_features

            benchmark_dir = Path(__file__).resolve().parent.parent.parent / "data" / "benchmarks"
            X, y = [], []

            if benchmark_dir.exists():
                for cls in ["HUMAN", "TRADITIONAL_AUTOMATION", "AGENTIC_AI"]:
                    cls_dir = benchmark_dir / cls.lower()
                    if cls_dir.exists():
                        for json_file in cls_dir.glob("*.json"):
                            try:
                                with open(json_file, "r", encoding="utf-8") as f:
                                    s = json.load(f)
                                f_dict = extract_all_features(s)
                                X.append(self.ml.extract_feature_vector(f_dict))
                                y.append(cls)
                            except Exception:
                                pass

            # If benchmark directory is empty or insufficient (< 12 samples), supplement with procedural seeds
            if len(X) < 12:
                from packages.generators.seed_data import generate_synthetic_session
                import random
                rng = random.Random(42)
                subtypes = {
                    "HUMAN": ["organic_mouse", "keyboard_focused"],
                    "TRADITIONAL_AUTOMATION": ["deterministic", "randomized", "evasive", "headless_dom"],
                    "AGENTIC_AI": ["trajectory_agent", "dom_agent", "hybrid_agent"],
                }
                for cls, st_list in subtypes.items():
                    for task in ["shopping", "travel", "forum"]:
                        for st in st_list:
                            for i in range(5):
                                s = generate_synthetic_session(cls, task, index=i, subtype=st, seed=rng.randint(0, 1000000))
                                f = extract_all_features(s)
                                X.append(self.ml.extract_feature_vector(f))
                                y.append(cls)

            self.ml.train(X, y)
        except Exception as e:
            print(f"[WebSense] WARNING: ML bootstrap failed — classifier will use heuristic fallback. Error: {e}")

    def evaluate_session(
        self,
        session_id: str,
        task: str,
        session_data: Dict[str, Any],
        features: Dict[str, Any],
        register_replay: bool = True,
    ) -> Dict[str, Any]:
        """
        Executes all 5 detection layers and synthesizes a unified actor verdict.

        register_replay: add this trajectory to the replay cache. The ingest path
        evaluates a page visit after every chunk, so it passes True only once
        (on the final chunk) to avoid filling the cache with snapshots of one visit.

        Signal hierarchy respected throughout:
          - Behavioral evidence drives classification
          - Environmental signals (webdriver) are supporting only
          - No single signal determines the final class
        """
        n_mouse = len(session_data.get("mouse_events", []))
        n_key = len(session_data.get("keyboard_events", []))
        n_click = len(session_data.get("click_events", []))
        n_scroll = len(session_data.get("scroll_events", []))
        n_tasks = len(session_data.get("task_actions", []))
        total_interactions = (
            n_mouse + n_key + n_click + n_scroll + n_tasks
            + features.get("total_event_count", 0)
        )

        is_synthetic = bool(session_data.get("is_synthetic"))

        # Layer 1 Rules: evaluate flags and environmental signals
        rule_score, rule_flags, rule_mitigations = self.rules.evaluate(features)

        # Minimum interaction gating:
        # A session must have minimum behavioral signal to perform reliable classification.
        # Sparse sessions (< 5 total events or single isolated click/key without trajectory)
        # have degenerate statistical distributions and cannot distinguish Human vs Bot vs Agent.
        has_sufficient_signal = is_synthetic or (
            (n_mouse >= 5 and features.get("path_length", 0) >= 15)
            or n_key >= 3
            or n_tasks >= 2
            or (total_interactions >= 5 and (n_click >= 2 or n_scroll >= 2))
            or total_interactions >= 10
        )

        if total_interactions == 0 or not has_sufficient_signal:
            reason = (
                "zero events recorded"
                if total_interactions == 0
                else f"insufficient events ({total_interactions} recorded; minimum 5 diverse events required for kinematic analysis)"
            )
            return {
                "final_verdict": "UNCERTAIN",
                "confidence": 50.0,
                "risk_score": 0.0,
                "l1_rule_score": rule_score if rule_score > 0 else 0.0,
                "l1_flags": rule_flags,
                "l2_ml_pred": "UNCERTAIN",
                "l2_ml_confidence": 50.0,
                "l2_ml_probabilities": {"UNCERTAIN": 1.0},
                "l3_anomaly_score": 0.0,
                "l3_is_anomaly": False,
                "l4_replay_similarity": 0.0,
                "l4_matched_session_id": None,
                "l4_is_replay": False,
                "l5_context_valid": True,
                "l5_status": "not_applicable",
                "contributing_signals": [
                    f"Low-signal telemetry: {reason}. Classified as UNCERTAIN to prevent false positive attribution on sparse interaction data."
                ],
                "counter_signals": [],
                "human_explanation": (
                    f"Classification is Uncertain (50% confidence). "
                    f"Low-signal telemetry: {reason}. "
                    f"The session does not contain sufficient kinematic or temporal data to reliably determine actor class. "
                    f"Classification is an evidence-based behavioral estimate."
                ),
                "fallback_used": True,
                "model_version": MODEL_VERSION,
            }

        # --- Layer 1: Rules ---
        rule_score, rule_flags, rule_mitigations = self.rules.evaluate(features)

        # --- Layer 2: Behavioral ML ---
        ml_pred, ml_conf, ml_probs = self.ml.predict(features)

        # --- Layer 3: Anomaly Detection ---
        anom_score, is_anom, anom_reasons = self.anomaly.score(features)

        # --- Layer 4: Replay Detection ---
        mouse_events = session_data.get("mouse_events", [])
        replay_sim, matched_id, is_replay = self.replay.check_replay(session_id, mouse_events)
        if register_replay:
            self.replay.register_session(session_id, mouse_events)

        # --- Layer 5: Contextual Validation ---
        task_actions = session_data.get("task_actions", [])
        click_events = session_data.get("click_events", [])
        ctx_valid, ctx_violations = self.context.validate(task, task_actions, click_events, features)
        if ctx_violations:
            l5_status = "violated"
        elif task in WORKFLOW_TASKS:
            l5_status = "valid"
        else:
            # No workflow rules for general/custom tasks: never report "valid".
            l5_status = "not_applicable"

        # --- Synthesize Risk Score (Behavioral signals first, environmental supporting) ---
        contributing_signals = []
        counter_signals = []
        risk = 0.0

        # ── BEHAVIORAL SIGNALS (primary — full weight) ────────────────────────

        # Mouse trajectory
        straightness = features.get("straightness_ratio", 0.7)
        key_cv = features.get("key_latency_cv", 0.0)
        key_count = features.get("key_event_count", 0)
        key_hold = features.get("key_mean_hold_time", 0.0)
        has_robotic_hold = (0.0 < key_hold < 35.0)

        # Evasive bots injecting Gaussian coordinate noise:
        # Evasive bots add artificial jitter to simulate tremor, but they lack human neuromuscular
        # target deceleration (Fitts's law), have sparse micro-corrections (<30), and uniform typing cadence.
        target_decel = features.get("target_approach_deceleration_ratio", 1.0)
        autocorr = features.get("velocity_autocorrelation", 0.0)
        path_len = features.get("path_length", 0.0)
        is_artificial_jitter = (
            straightness < 0.80
            and features.get("micro_corrections", 0) < 30
            and target_decel > 0.35
            and (key_count >= 4 and (key_cv < 0.22 or has_robotic_hold))
        )
        if is_artificial_jitter:
            contributing_signals.append(
                f"Artificial coordinate jitter detected (target decel: {target_decel:.2f}, micro-corrections: {features.get('micro_corrections', 0)}) — evasive bot spoofing human tremor"
            )
            risk += 35.0

        # Fitts's Law Target Approach Deceleration (human motor control confirmation)
        if target_decel < 0.35 and straightness < 0.90 and not is_artificial_jitter:
            counter_signals.append("Fitts's law target deceleration verified (natural neuromuscular motor control)")
            risk -= 20.0

        if straightness > 0.95 and features.get("micro_corrections", 0) <= 2 and path_len > 100:
            contributing_signals.append(
                f"Abnormally linear mouse trajectory (straightness: {straightness:.2f}) — consistent with scripted automation"
            )
            risk += 25.0
        elif (straightness < 0.90 or features.get("micro_corrections", 0) >= 3) and not is_artificial_jitter and (key_count < 4 or (key_cv >= 0.20 and not has_robotic_hold)):
            counter_signals.append(
                f"Natural human trajectory dynamics with {features.get('micro_corrections', 0)} micro-corrections"
            )
            risk -= 25.0

        # Keystroke cadence
        if key_count >= 4 and (key_cv < 0.18 or has_robotic_hold):
            contributing_signals.append(
                f"Synthetic uniform typing cadence (CV: {key_cv:.3f}, hold: {key_hold:.0f}ms) — characteristic of automation"
            )
            risk += 30.0
        elif key_count >= 4 and key_cv > 0.20 and not has_robotic_hold:
            counter_signals.append(f"Organic typing rhythm variation (CV: {key_cv:.2f}, hold: {key_hold:.0f}ms)")
            risk -= 15.0

        # Keyboard-only / assistive navigation: natural typing rhythm without mouse movement
        is_keyboard_human = (path_len == 0 and key_count >= 4 and key_cv >= 0.20 and not has_robotic_hold)
        if is_keyboard_human:
            counter_signals.append(
                f"Organic keyboard-only interaction pattern (CV: {key_cv:.2f}) — assistive or keyboard-centric navigation"
            )
            risk -= 15.0

        # Agentic agency profile signals
        planning_pause_ratio = features.get("planning_pause_ratio", 0.0)
        llm_gap_ratio = features.get("llm_inference_gap_ratio", 0.0)
        action_burst = features.get("action_burstiness_score", 0.0)
        nav_segments = features.get("nav_segment_count", 0)
        adaptation_score = features.get("adaptation_score", 0.0)
        action_interval_var = features.get("action_interval_variance", 0.0)
        action_interval_mean = features.get("action_interval_mean_ms", 0.0)
        interaction_diversity = features.get("interaction_diversity_score", 0.0)

        if planning_pause_ratio > 0.30 or llm_gap_ratio > 0.25:
            contributing_signals.append(
                f"Goal-directed deliberation pauses ({planning_pause_ratio:.0%} of session time, LLM gap ratio: {llm_gap_ratio:.0%}) — agentic planning signature"
            )
            risk += 15.0  # Shifts toward AGENTIC_AI, not TRADITIONAL_AUTOMATION

        if nav_segments >= 3:
            contributing_signals.append(
                f"Segmented cursor navigation ({nav_segments} distinct path segments) — autonomous task navigation"
            )
            risk += 10.0

        if adaptation_score > 0.4:
            contributing_signals.append(
                f"Action adaptation pattern detected (score: {adaptation_score:.2f}) — context-sensitive decision making"
            )

        # Replay signal
        if is_replay:
            contributing_signals.append(
                f"High-confidence trajectory replay match ({replay_sim * 100:.1f}% DTW similarity to session {matched_id})"
            )
            risk += 50.0

        # Context violations
        if not ctx_valid:
            for v in ctx_violations:
                contributing_signals.append(f"Task workflow violation: {v}")
            risk += 35.0

        # Anomaly signal
        if is_anom:
            for r in anom_reasons:
                contributing_signals.append(f"Behavioral anomaly: {r}")
            risk += 15.0

        # Dwell time — human positive signal
        if features.get("duration_ms", 0) > 3000 and features.get("pause_count", 0) >= 1:
            counter_signals.append("Normal human cognitive dwell time and pause distribution")
            risk -= 10.0

        # ── ENVIRONMENTAL SIGNALS (supporting — reduced weight 0.25x) ─────────
        # webdriver_flag contributes at 25% of its rule_score weight
        env_contribution = rule_score * 0.25
        risk_score = round(max(0.0, min(100.0, risk + env_contribution)), 1)

        # Note: env signals are summarized in rule_flags but NOT used as primary classifier

        # ── ACTOR CLASSIFICATION LOGIC ────────────────────────────────────────

        final_verdict = "UNCERTAIN"
        confidence = 50.0
        fallback_used = False

        # Organic human kinematics protection: humans naturally have micro-corrections (hand tremor)
        # and curved Bézier paths. An organic human pausing to read must not be called AGENTIC_AI.
        # But if artificial jitter is detected (high jerk, negative autocorrelation), it cannot be human!
        is_organic_human_kinematics = (
            path_len > 80
            and not is_artificial_jitter
            and (features.get("micro_corrections", 0) >= 4 or (features.get("micro_corrections", 0) >= 2 and straightness < 0.88))
            and not features.get("webdriver_flag")
            and (key_count < 4 or (key_cv >= 0.20 and not has_robotic_hold))
        )

        has_llm_deliberation = (
            llm_gap_ratio > 0.20
            or (action_interval_mean >= 1200 and action_interval_var >= 400)
            or (action_burst > 0.30 and planning_pause_ratio > 0.15)
        )

        has_agency_signal = (
            has_llm_deliberation or
            planning_pause_ratio > 0.15 or
            nav_segments >= 2 or
            adaptation_score > 0.35 or
            action_interval_var > 800
        )
        is_agentic_profile = (
            has_agency_signal
            and not is_organic_human_kinematics
            and (
                has_llm_deliberation or
                (planning_pause_ratio > 0.30 and nav_segments >= 3 and straightness > 0.80) or
                (adaptation_score > 0.45 and features.get("micro_corrections", 0) <= 2 and nav_segments >= 3) or
                (features.get("first_action_delay_ms", 0) > 500 and nav_segments >= 4 and straightness > 0.80) or
                (action_interval_var > 1200 and nav_segments >= 3 and straightness > 0.80) or  # Strong LLM inference-delay signature
                (len(task_actions) >= 2 and action_interval_var > 800 and planning_pause_ratio > 0.20 and features.get("micro_corrections", 0) <= 2) or  # Workflow / computer-use agent
                (path_len < 50 and len(task_actions) >= 2 and (planning_pause_ratio > 0.20 or llm_gap_ratio > 0.20)) or  # DOM-driven agent without cursor trajectory
                (ml_pred == "AGENTIC_AI" and ml_conf >= 68.0 and rule_score < 60.0)  # Corroborated ML prediction
            )
        )

        # Traditional automation profile: highly uniform, deterministic behavior.
        # Blocked if genuine LLM deliberation is present (LLM agents wait multi-seconds for tokens).
        is_automation_profile = (
            (
                is_replay or
                is_artificial_jitter or
                rule_score >= 35.0 or
                (key_count >= 4 and (key_cv < 0.18 or (0 < key_hold < 35.0))) or
                (straightness > 0.92 and key_count >= 4 and (key_cv < 0.20 or features.get("micro_corrections", 0) <= 1)) or
                (features.get("duration_ms", 1000) < 500 and features.get("total_event_count", 0) >= 5) or
                (ml_pred == "TRADITIONAL_AUTOMATION" and ml_conf >= 65.0 and not is_keyboard_human)
            ) and not is_agentic_profile and not has_llm_deliberation  # Never override agentic LLM evidence
        )

        # Calibrated confidence computation:
        # Harmonize Layer-2 calibrated posterior probability (65%) with multi-layer corroboration (35%)
        calibrated_conf = ml_conf
        if ml_probs and isinstance(ml_probs, dict):
            # If ml_probs contains calibrated probabilities for the predicted class
            top_prob = ml_probs.get(ml_pred, 0.5)
            calibrated_conf = top_prob * 100.0 if top_prob <= 1.0 else top_prob

        if is_agentic_profile:
            final_verdict = "AGENTIC_AI"
            c_target = ml_probs.get("AGENTIC_AI", calibrated_conf / 100.0) * 100.0 if ml_probs else calibrated_conf
            heuristic_conf = min(94.0, max(55.0, 38.0 + (risk_score * 0.93)))
            confidence = round(min(98.0, max(55.0, (c_target * 0.65) + (heuristic_conf * 0.35))), 1)
            risk_score = max(35.0, risk_score)
            contributing_signals.append(
                "Agentic behavior profile: autonomous goal-directed navigation, "
                "planning pause cadence, and context-dependent action selection"
            )

        elif is_automation_profile:
            final_verdict = "TRADITIONAL_AUTOMATION"
            c_target = ml_probs.get("TRADITIONAL_AUTOMATION", calibrated_conf / 100.0) * 100.0 if ml_probs else calibrated_conf
            heuristic_conf = min(99.0, max(50.0, 42.0 + (risk_score * 0.95)))
            confidence = round(min(99.0, max(52.0, (c_target * 0.65) + (heuristic_conf * 0.35))), 1)
            risk_score = max(50.0, risk_score)
            contributing_signals.append("Deterministic scripted behavior signature: uniform timing, predictable sequence")

        # Webdriver detected but behavior is not clearly automation — could be unmasked agent
        elif features.get("webdriver_flag", 0.0) == 1.0:
            if ml_pred == "AGENTIC_AI" and ml_conf >= 65.0:
                final_verdict = "AGENTIC_AI"
                confidence = round(min(88.0, max(55.0, calibrated_conf)), 1)
                risk_score = max(40.0, risk_score)
                contributing_signals.append(
                    "Automated browser environment combined with agentic behavioral profile"
                )
            elif ml_pred == "TRADITIONAL_AUTOMATION" or ml_conf >= 72.0:
                final_verdict = "TRADITIONAL_AUTOMATION"
                confidence = round(min(92.0, max(58.0, calibrated_conf)), 1)
                risk_score = max(50.0, risk_score)
            else:
                final_verdict = "UNCERTAIN"
                confidence = 48.0
                fallback_used = True

        elif risk_score <= 30.0 and rule_score < 30.0 and (ml_pred == "HUMAN" or is_keyboard_human):
            final_verdict = "HUMAN"
            c_target = ml_probs.get("HUMAN", calibrated_conf / 100.0) * 100.0 if ml_probs else calibrated_conf
            heuristic_conf = min(98.0, max(68.0, 100.0 - (risk_score * 1.1)))
            confidence = round(min(98.0, max(68.0, (c_target * 0.65) + (heuristic_conf * 0.35))), 1)

        elif ml_conf >= 78.0:
            final_verdict = ml_pred
            confidence = round(calibrated_conf, 1)
            if final_verdict in ("TRADITIONAL_AUTOMATION", "AGENTIC_AI"):
                risk_score = max(45.0, risk_score)

        else:
            final_verdict = "UNCERTAIN"
            confidence = round(max(40.0, min(65.0, 50.0 + (calibrated_conf - 50.0) * 0.5)), 1)
            fallback_used = True

        # ── GENERATE HUMAN-READABLE EXPLANATION ───────────────────────────────

        disclaimer = (
            "Classification is an evidence-based behavioral estimate. "
            "It does not directly identify the software or model controlling the browser."
        )

        if final_verdict == "HUMAN":
            explanation = (
                f"Classified as Human ({confidence:.0f}% confidence, risk {risk_score:.0f}/100). "
                f"Demonstrated organic motor variability: {features.get('micro_corrections', 0)} micro-corrections, "
                f"natural trajectory curvature ({straightness:.2f} straightness), and realistic cognitive pacing. "
                f"{disclaimer}"
            )
        elif final_verdict == "TRADITIONAL_AUTOMATION":
            explanation = (
                f"Classified as Traditional Automation ({confidence:.0f}% confidence, risk {risk_score:.0f}/100). "
                f"Exhibits deterministic automation indicators: "
                f"{', '.join(contributing_signals[:2]) if contributing_signals else 'high rule score'}. "
                f"{disclaimer}"
            )
        elif final_verdict == "AGENTIC_AI":
            explanation = (
                f"Classified as Agentic AI ({confidence:.0f}% confidence, risk {risk_score:.0f}/100). "
                f"Exhibits autonomous agent behavioral profile: goal-directed multi-step navigation, "
                f"deliberate planning pauses, and context-sensitive action selection. "
                f"{disclaimer}"
            )
        else:
            explanation = (
                f"Classification is Uncertain ({confidence:.0f}% confidence). "
                f"Mixed signals observed — insufficient behavioral evidence for confident actor classification. "
                f"{disclaimer}"
            )

        return {
            "l1_rule_score": rule_score,
            "l1_flags": rule_flags,
            "l2_ml_pred": ml_pred,
            "l2_ml_confidence": ml_conf,
            "l2_ml_probabilities": ml_probs,
            "l3_anomaly_score": anom_score,
            "l3_is_anomaly": is_anom,
            "l4_replay_similarity": replay_sim,
            "l4_matched_session_id": matched_id,
            "l4_is_replay": is_replay,
            "l5_context_valid": ctx_valid,
            "l5_context_violations": ctx_violations,
            "l5_status": l5_status,
            "final_verdict": final_verdict,
            "confidence": confidence,
            "risk_score": risk_score,
            "contributing_signals": contributing_signals,
            "counter_signals": counter_signals,
            "human_explanation": explanation,
            "fallback_used": fallback_used,
            "model_version": MODEL_VERSION
        }

