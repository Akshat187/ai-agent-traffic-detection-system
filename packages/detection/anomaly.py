"""
Layer 3: Behavioral Anomaly Detection Engine.
Assesses whether a session's interaction dynamics deviate from normal human baseline distributions.
"""

import math
from typing import Dict, Any, Tuple, List

# Core features used to measure behavioral deviation from normal human baseline
BASELINE_HUMAN_STATS = {
    "straightness_ratio": {"mean": 0.72, "std": 0.12, "min": 0.35, "max": 0.92},
    "mean_velocity": {"mean": 450.0, "std": 180.0, "min": 50.0, "max": 1200.0},
    "velocity_std": {"mean": 380.0, "std": 160.0, "min": 30.0, "max": 1100.0},
    "micro_corrections": {"mean": 6.5, "std": 3.8, "min": 1, "max": 25},
    "key_latency_cv": {"mean": 0.38, "std": 0.15, "min": 0.12, "max": 0.95},
    "first_action_delay_ms": {"mean": 1250.0, "std": 650.0, "min": 180.0, "max": 8000.0}
}


class AnomalyDetector:
    """Detects statistical outliers and out-of-distribution sessions."""

    def __init__(self, contamination: float = 0.08):
        self.contamination = contamination
        self.sklearn_iso = None
        self.baseline_stats = BASELINE_HUMAN_STATS

    def score(self, features: Dict[str, Any]) -> Tuple[float, bool, List[str]]:
        """
        Calculates anomaly score: -1.0 (severe outlier) to +1.0 (highly typical).
        Returns (score, is_anomaly, outlier_reasons).
        """
        deviations = []
        z_scores = []

        for feat, stat in self.baseline_stats.items():
            val = float(features.get(feat, stat["mean"]))
            mean = stat["mean"]
            std = max(1e-5, stat["std"])
            z = (val - mean) / std
            z_scores.append(abs(z))

            # Specific anomaly checks
            if feat == "straightness_ratio" and val > 0.95:
                deviations.append("Abnormally straight trajectory (> 0.95)")
            elif feat == "micro_corrections" and val == 0 and features.get("mouse_event_count", 0) > 10:
                deviations.append("Complete absence of natural human micro-corrections")
            elif feat == "key_latency_cv" and val < 0.06 and features.get("key_event_count", 0) >= 5:
                deviations.append("Zero keystroke timing variance (synthetic rhythm)")
            elif feat == "first_action_delay_ms" and 0 < val < 50:
                deviations.append("Sub-50ms reaction time beyond human perceptual limits")

        # Mean z-score across feature dimensions
        mean_z = sum(z_scores) / len(z_scores) if z_scores else 0.0

        # Anomaly score mapped to [-1, 1]
        # Normal human: z ~ 0 to 1.5 -> score ~ 0.5 to 0.9
        # Bot / Outlier: z > 3.0 -> score < 0.0
        score = 1.0 - (mean_z / 3.0)
        score = max(-1.0, min(1.0, score))

        is_anomaly = score < 0.0 or len(deviations) >= 2

        return round(score, 3), is_anomaly, deviations
