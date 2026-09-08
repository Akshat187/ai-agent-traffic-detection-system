"""
Layer 4: Historical Trajectory Replay Detection Engine.
Identifies synthetic trajectory replay attacks using spatial similarity and Dynamic Time Warping.
"""

from typing import List, Dict, Any, Tuple, Optional
from packages.core.dtw import compute_trajectory_similarity


class ReplayDetector:
    """Detects replay of identical or slightly perturbed previous mouse trajectories."""

    def __init__(self, similarity_threshold: float = 0.94, max_history_size: int = 50):
        self.similarity_threshold = similarity_threshold
        self.max_history_size = max_history_size
        self.session_cache: List[Dict[str, Any]] = []

    def register_session(self, session_id: str, mouse_events: List[Dict[str, Any]]):
        """Stores normalized trajectory in sliding window cache."""
        if mouse_events and len(mouse_events) >= 5:
            self.session_cache.append({
                "session_id": session_id,
                "mouse_events": mouse_events
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
        Returns (max_similarity, matched_session_id, is_replay).
        """
        if not current_mouse_events or len(current_mouse_events) < 5 or not self.session_cache:
            return 0.0, None, False

        max_sim = 0.0
        matched_id = None

        for item in self.session_cache:
            if item["session_id"] == current_session_id:
                continue
            sim = compute_trajectory_similarity(current_mouse_events, item["mouse_events"])
            if sim > max_sim:
                max_sim = sim
                matched_id = item["session_id"]

        is_replay = max_sim >= self.similarity_threshold

        return round(max_sim, 4), matched_id if is_replay else None, is_replay
