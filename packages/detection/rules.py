"""
Layer 1: Rule-Based Detection Engine.

Applies deterministic heuristics and behavioral physics thresholds to distinguish
actor classes. Environment signals (webdriver) are supporting evidence only —
they never independently determine the final classification.

Signal Hierarchy:
  STRONGER — behavioral / contextual:
    - action timing patterns
    - trajectory characteristics
    - typing rhythm
    - scrolling behavior
    - interaction diversity
    - planning pauses

  SUPPORTING — environmental:
    - browser automation indicators (webdriver)
    - browser characteristics
    - environment inconsistencies
"""

from typing import Dict, Any, Tuple, List


class RuleEngine:
    """Configurable rule-based detection engine with explainable point scoring.

    Scores indicate automation likelihood — high scores indicate TRADITIONAL_AUTOMATION
    or AGENTIC_AI patterns. webdriver flag contributes at reduced weight as a
    supporting environmental signal, not primary evidence.
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {
            # Behavioral signals (strong) — can each independently shift score
            "zero_mouse_with_clicks_penalty": 40.0,
            "perfect_straightness_penalty": 30.0,
            "uniform_keystrokes_penalty": 35.0,
            "instant_completion_penalty": 35.0,
            "superhuman_reaction_penalty": 25.0,
            "planning_pause_bonus": 20.0,       # Supporting agentic pattern
            "segmented_trajectory_bonus": 15.0, # Supporting agentic pattern

            # Environmental signals (supporting only) — reduced weight
            "webdriver_supporting_penalty": 20.0,  # Was 50 — now supporting signal only

            # Human mitigation bonuses
            "human_micro_correction_bonus": 30.0,
            "human_keystroke_jitter_bonus": 20.0,
            "human_dwell_bonus": 15.0,
        }

    def evaluate(self, features: Dict[str, Any]) -> Tuple[float, List[str], List[str]]:
        """
        Evaluates features and returns (rule_score 0-100, automation_flags, human_signals).

        Signal hierarchy is respected:
          - Behavioral signals contribute first and at full weight
          - Environmental signals (webdriver) contribute at reduced weight as supporting evidence
          - Absence of webdriver does NOT indicate human behavior
        """
        risk = 0.0
        flags = []
        mitigations = []

        # ── BEHAVIORAL SIGNALS (primary) ──────────────────────────────────────

        # 1. Clicks present but zero or almost no mouse movement
        click_count = features.get("click_count", 0)
        mouse_count = features.get("mouse_event_count", 0)
        if click_count > 0 and mouse_count < 3:
            risk += self.config["zero_mouse_with_clicks_penalty"]
            flags.append("DOM_CLICKS_WITHOUT_MOUSE_TRAJECTORY")

        # 2. Perfectly straight mouse movements (automation signature)
        straightness = features.get("straightness_ratio", 1.0)
        path_length = features.get("path_length", 0.0)
        if straightness > 0.96 and path_length > 150:
            risk += self.config["perfect_straightness_penalty"]
            flags.append("ABNORMAL_LINEAR_MOUSE_PATH")

        # 3. Uniform typing cadence or superhuman key hold speed
        key_count = features.get("key_event_count", 0)
        key_cv = features.get("key_latency_cv", 0.0)
        key_hold = features.get("key_mean_hold_time", 0.0)
        if key_count >= 4 and (key_cv < 0.18 or (0 < key_hold < 35.0)):
            risk += self.config["uniform_keystrokes_penalty"]
            flags.append("SYNTHETIC_UNIFORM_KEYSTROKE_CADENCE")

        # 4. Instantaneous task completion (<300ms with multiple events)
        duration_ms = features.get("duration_ms", 1000.0)
        total_events = features.get("total_event_count", 0)
        if duration_ms < 300.0 and total_events >= 5:
            risk += self.config["instant_completion_penalty"]
            flags.append("IMPOSSIBLE_SUB_SECOND_TASK_COMPLETION")

        # 5. Superhuman first action delay (<40ms from page load)
        first_action = features.get("first_action_delay_ms", 500.0)
        if 0 < first_action < 40.0:
            risk += self.config["superhuman_reaction_penalty"]
            flags.append("SUPERHUMAN_FIRST_ACTION_LATENCY")

        # 6. Agentic: planning pauses detected (deliberate pre-action deliberation)
        planning_pause_ratio = features.get("planning_pause_ratio", 0.0)
        nav_segments = features.get("nav_segment_count", 0)
        if planning_pause_ratio > 0.30 and nav_segments >= 3:
            flags.append("PLANNING_PAUSE_DELIBERATION_PATTERN")
            # Note: this is an agentic signal, not an automation risk boost

        # 7. Segmented trajectory (agentic hallmark)
        if nav_segments >= 4 and straightness > 0.80 and straightness < 0.98:
            flags.append("SEGMENTED_GOAL_DIRECTED_TRAJECTORY")

        # ── ENVIRONMENTAL SIGNALS (supporting only) ───────────────────────────

        # 8. Browser automation environment (SUPPORTING SIGNAL ONLY)
        # This signal supports but does not determine classification.
        # Absence does NOT prove human behavior — sophisticated agents mask this.
        if features.get("webdriver_flag", 0.0) == 1.0:
            risk += self.config["webdriver_supporting_penalty"]
            flags.append("AUTOMATION_BROWSER_ENV_DETECTED")
            # Add clarifying note that this is environmental evidence
            flags.append("NOTE_ENV_SIGNAL_SUPPORTING_ONLY")

        # ── HUMAN MITIGATION SIGNALS ──────────────────────────────────────────

        micro_corrections = features.get("micro_corrections", 0)
        has_robotic_hold = (0.0 < key_hold < 35.0)

        if (micro_corrections >= 3 and straightness < 0.85 and 
            (key_count < 4 or (key_cv >= 0.20 and not has_robotic_hold))):
            risk -= self.config["human_micro_correction_bonus"]
            mitigations.append("NATURAL_MOUSE_MICRO_JITTER_DETECTED")

        if key_count >= 5 and key_cv > 0.20 and not has_robotic_hold:
            risk -= self.config["human_keystroke_jitter_bonus"]
            mitigations.append("ORGANIC_KEYSTROKE_TIMING_VARIATION")

        if duration_ms > 8000.0 and features.get("pause_count", 0) >= 1 and not has_robotic_hold:
            risk -= self.config["human_dwell_bonus"]
            mitigations.append("NATURAL_COGNITIVE_DWELL_TIME")

        rule_score = max(0.0, min(100.0, risk))
        return round(rule_score, 2), flags, mitigations




