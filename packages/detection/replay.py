"""
Layer 4: Historical Trajectory Replay Detection Engine.
Identifies synthetic trajectory replay attacks using spatial similarity and Dynamic Time Warping.
"""

from typing import List, Dict, Any, Tuple, Optional
from packages.core.dtw import (
    normalize_and_resample_trajectory,
    compute_bounding_box_aspect,
    compute_resampled_similarity,
)


class ReplayDetector:
    """Detects replay of identical or slightly perturbed previous mouse trajectories."""

    def __init__(
        self,
        similarity_threshold: float = 0.94,
        max_history_size: int = 25,
        max_compare_window: int = 15,
    ):
        self.similarity_threshold = similarity_threshold
        self.max_history_size = max_history_size
        self.max_compare_window = max_compare_window
        self.session_cache: List[Dict[str, Any]] = []

    def register_session(self, session_id: str, mouse_events: List[Dict[str, Any]]):
        """Stores pre-normalized trajectory and geometry metadata in sliding window cache."""
        if mouse_events and len(mouse_events) >= 5:
            self.session_cache = [s for s in self.session_cache if s["session_id"] != session_id]
            self.session_cache.append({
                "session_id": session_id,
                "mouse_events": mouse_events,
                "resampled": normalize_and_resample_trajectory(mouse_events, num_points=40),
                "aspect_ratio": compute_bounding_box_aspect(mouse_events),
                "event_count": len(mouse_events),
            })
            if len(self.session_cache) > self.max_history_size:
                self.session_cache.pop(0)

    def check_replay(
        self,
        current_session_id: str,
        current_mouse_events: List[Dict[str, Any]]
    ) -> Tuple[float, Optional[str], bool]:
        """
        Compares current mouse trajectory with cached recent sessions.
        Pre-filters candidates by bounding-box aspect ratio and event count before DTW.
        Returns (max_similarity, matched_session_id, is_replay).
        """
        if not current_mouse_events or len(current_mouse_events) < 5 or not self.session_cache:
            return 0.0, None, False

        curr_aspect = compute_bounding_box_aspect(current_mouse_events)
        curr_count = len(current_mouse_events)
        curr_resampled = normalize_and_resample_trajectory(current_mouse_events, num_points=40)

        max_sim = 0.0
        matched_id = None

        # Cap sliding historical cache comparison window to most recent candidates
        candidates = self.session_cache[-self.max_compare_window:]
        for item in reversed(candidates):
            if item["session_id"] == current_session_id:
                continue

            # Fast geometric pre-filter: skip DTW if bounding-box aspect or path length diverges sharply
            cached_aspect = item.get("aspect_ratio", 1.0)
            if abs(curr_aspect - cached_aspect) / max(curr_aspect, cached_aspect, 1e-6) > 0.35:
                continue
            cached_count = item.get("event_count", 0)
            if cached_count > 0 and (min(curr_count, cached_count) / max(curr_count, cached_count)) < 0.40:
                continue

            sim = compute_resampled_similarity(curr_resampled, item["resampled"])
            if sim > max_sim:
                max_sim = sim
                matched_id = item["session_id"]
                if max_sim >= self.similarity_threshold:
                    break

        is_replay = max_sim >= self.similarity_threshold

        return round(max_sim, 4), matched_id if is_replay else None, is_replay
