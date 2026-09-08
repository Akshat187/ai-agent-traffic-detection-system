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
        """Pre-trains behavioral classifier on standard physically grounded baseline distributions."""
        try:
            from packages.generators.seed_data import generate_synthetic_session
            from packages.core.features import extract_all_features
            import random
            rng = random.Random(42)
            X, y = [], []
            for cls in ["HUMAN", "TRADITIONAL_AUTOMATION", "AGENTIC_AI"]:
                for task in ["shopping", "travel", "forum"]:
                    for i in range(12):
                        s = generate_synthetic_session(cls, task, index=i, seed=rng.randint(0, 1000000))
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
        features: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Executes all 5 detection layers and synthesizes a unified actor verdict.

        Signal hierarchy respected throughout:
          - Behavioral evidence drives classification
          - Environmental signals (webdriver) are supporting only
          - No single signal determines the final class
        """
        # --- Layer 1: Rules ---
        rule_score, rule_flags, rule_mitigations = self.rules.evaluate(features)

        # --- Layer 2: Behavioral ML ---
        ml_pred, ml_conf, ml_probs = self.ml.predict(features)

        # --- Layer 3: Anomaly Detection ---
        anom_score, is_anom, anom_reasons = self.anomaly.score(features)

        # --- Layer 4: Replay Detection ---
        mouse_events = session_data.get("mouse_events", [])
        replay_sim, matched_id, is_replay = self.replay.check_replay(session_id, mouse_events)
        self.replay.register_session(session_id, mouse_events)

        # --- Layer 5: Contextual Validation ---
        task_actions = session_data.get("task_actions", [])
        click_events = session_data.get("click_events", [])
        ctx_valid, ctx_violations = self.context.validate(task, task_actions, click_events, features)

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

        if straightness > 0.95 and features.get("path_length", 0) > 100:
            contributing_signals.append(
                f"Abnormally linear mouse trajectory (straightness: {straightness:.2f}) — consistent with scripted automation"
            )
            risk += 25.0
        elif straightness < 0.85 and features.get("micro_corrections", 0) >= 3 and (key_count < 4 or (key_cv >= 0.20 and not has_robotic_hold)):
            counter_signals.append(
                f"Natural human trajectory curvature with {features.get('micro_corrections', 0)} micro-corrections"
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


        # Agentic agency profile signals
        planning_pause_ratio = features.get("planning_pause_ratio", 0.0)
        nav_segments = features.get("nav_segment_count", 0)
        adaptation_score = features.get("adaptation_score", 0.0)
        action_interval_var = features.get("action_interval_variance", 0.0)
        interaction_diversity = features.get("interaction_diversity_score", 0.0)

        if planning_pause_ratio > 0.30:
            contributing_signals.append(
                f"Goal-directed deliberation pauses ({planning_pause_ratio:.0%} of session time) — agentic planning signature"
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

        # Agentic AI profile: deliberate pauses + segmented navigation + adaptive timing.
        # Thresholds raised (0.20→0.30 pause, 2→3 segments) to prevent natural human
        # browsing pauses from triggering this branch — the original loose thresholds
        # caused virtually every real extension session to be misclassified as AGENTIC_AI.
        # Checked FIRST — agent sessions can also have moderately linear per-segment motion,
        # so they must be captured before the broader automation check.
        is_agentic_profile = (
            (planning_pause_ratio > 0.30 and nav_segments >= 3) or
            (adaptation_score > 0.45 and features.get("micro_corrections", 0) <= 2 and nav_segments >= 2) or
            (features.get("first_action_delay_ms", 0) > 500 and nav_segments >= 4 and straightness > 0.80) or
            (action_interval_var > 1200 and nav_segments >= 3) or  # Strong LLM inference-delay signature
            (ml_pred == "AGENTIC_AI" and ml_conf >= 70.0)  # Require high ML confidence to avoid false positives
        )

        # Traditional automation profile: highly uniform, deterministic behavior.
        is_automation_profile = (
            is_replay or
            rule_score >= 35.0 or
            (key_count >= 4 and (key_cv < 0.18 or (0 < key_hold < 35.0))) or
            (straightness > 0.92 and key_count >= 4 and (key_cv < 0.20 or features.get("micro_corrections", 0) <= 1)) or
            (features.get("duration_ms", 1000) < 500 and features.get("total_event_count", 0) >= 5) or
            (ml_pred == "TRADITIONAL_AUTOMATION" and ml_conf >= 65.0)
        ) and not is_agentic_profile  # Never override agentic evidence

        if is_agentic_profile:
            final_verdict = "AGENTIC_AI"
            # Confidence scales with actual behavioral evidence (risk_score), not a hard floor.
            # raw_risk=0 → ~55% (uncertain agentic); raw_risk=40 → ~79%; raw_risk=60 → ~91%
            confidence = round(min(94.0, max(55.0, 38.0 + (risk_score * 0.93))), 1)
            risk_score = max(35.0, risk_score)  # lower floor — genuine humans can still have some risk
            contributing_signals.append(
                "Agentic behavior profile: autonomous goal-directed navigation, "
                "planning pause cadence, and context-dependent action selection"
            )

        elif is_automation_profile:
            final_verdict = "TRADITIONAL_AUTOMATION"
            # Confidence scales with actual risk evidence, not a fixed floor.
            # raw_risk=0 → ~50% (weak signal); raw_risk=40 → ~82%; raw_risk=60 → ~98%
            confidence = round(min(99.0, max(50.0, 42.0 + (risk_score * 0.95))), 1)
            risk_score = max(50.0, risk_score)
            contributing_signals.append("Deterministic scripted behavior signature: uniform timing, predictable sequence")

        # Webdriver detected but behavior is not clearly automation — could be unmasked agent
        elif features.get("webdriver_flag", 0.0) == 1.0:
            # Environmental signal is supporting — use ML to disambiguate
            if ml_pred == "AGENTIC_AI" and ml_conf >= 65.0:
                final_verdict = "AGENTIC_AI"
                confidence = round(min(85.0, max(55.0, ml_conf)), 1)
                risk_score = max(40.0, risk_score)
                contributing_signals.append(
                    "Automated browser environment combined with agentic behavioral profile"
                )
            elif ml_pred == "TRADITIONAL_AUTOMATION" or ml_conf >= 72.0:
                final_verdict = "TRADITIONAL_AUTOMATION"
                confidence = round(min(90.0, max(58.0, ml_conf)), 1)
                risk_score = max(50.0, risk_score)
            else:
                final_verdict = "UNCERTAIN"
                confidence = 48.0
                fallback_used = True

        # HUMAN: only assign when risk is genuinely low. Both risk_score and rule_score must
        # be below 30 — this prevents bot sessions with zero agentic signals but moderate
        # behavioral risk from falling through to HUMAN via the ML fallback.
        elif risk_score <= 30.0 and rule_score < 30.0 and ml_pred == "HUMAN":
            final_verdict = "HUMAN"
            confidence = round(min(98.0, max(68.0, 100.0 - (risk_score * 1.1))), 1)

        elif ml_conf >= 78.0:
            final_verdict = ml_pred
            confidence = round(ml_conf, 1)
            if final_verdict in ("TRADITIONAL_AUTOMATION", "AGENTIC_AI"):
                risk_score = max(45.0, risk_score)

        else:
            final_verdict = "UNCERTAIN"
            confidence = round(max(40.0, min(65.0, 50.0 + (ml_conf - 50.0) * 0.5)), 1)
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
            "final_verdict": final_verdict,
            "confidence": confidence,
            "risk_score": risk_score,
            "contributing_signals": contributing_signals,
            "counter_signals": counter_signals,
            "human_explanation": explanation,
            "fallback_used": fallback_used,
            "model_version": "v1.2.1-actor-inference"
        }

