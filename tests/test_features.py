"""
Unit Tests for Kinematics and Feature Extraction.
"""

import pytest
from packages.core.kinematics import calculate_kinematics, compute_distance
from packages.core.features import extract_keyboard_features, extract_all_features
from packages.core.dtw import compute_trajectory_similarity, normalize_and_resample_trajectory


def test_compute_distance():
    assert compute_distance((0, 0), (3, 4)) == 5.0
    assert compute_distance((10, 10), (10, 10)) == 0.0


def test_straight_line_kinematics():
    """A straight robotic line should have straightness_ratio == 1.0 and zero micro_corrections."""
    straight_events = [
        {"x": 100 + i * 50, "y": 100 + i * 50, "t": i * 30, "type": "move"}
        for i in range(10)
    ]
    res = calculate_kinematics(straight_events)
    assert res["straightness_ratio"] >= 0.98
    assert res["micro_corrections"] == 0
    assert res["mean_velocity"] > 0.0


def test_curved_human_kinematics():
    """Curved path with jitter should have lower straightness ratio and micro corrections."""
    curved_events = [
        {"x": 100, "y": 100, "t": 0, "type": "move"},
        {"x": 140, "y": 120, "t": 30, "type": "move"},
        {"x": 180, "y": 160, "t": 60, "type": "move"},
        {"x": 190, "y": 150, "t": 90, "type": "move"},  # micro-correction oscillation
        {"x": 230, "y": 210, "t": 120, "type": "move"},
        {"x": 300, "y": 280, "t": 150, "type": "move"}
    ]
    res = calculate_kinematics(curved_events)
    assert res["straightness_ratio"] < 1.0
    assert res["path_length"] > res["direct_distance"]


def test_keyboard_features_uniform_vs_variable():
    """Bot uniform typing (CV ~0) vs Human variable typing (CV > 0.25)."""
    bot_keys = [{"t": i * 50, "interval": 50, "hold": 20, "is_paste": False} for i in range(10)]
    bot_res = extract_keyboard_features(bot_keys)
    assert bot_res["key_latency_cv"] < 0.01

    human_keys = [
        {"t": 100, "interval": 120, "hold": 60, "is_paste": False},
        {"t": 350, "interval": 250, "hold": 80, "is_paste": False},
        {"t": 440, "interval": 90, "hold": 45, "is_paste": False},
        {"t": 750, "interval": 310, "hold": 75, "is_paste": False}
    ]
    human_res = extract_keyboard_features(human_keys)
    assert human_res["key_latency_cv"] > 0.20


def test_dtw_trajectory_similarity():
    """Identical trajectories must have ~1.0 similarity; divergent paths must have lower similarity."""
    traj1 = [{"x": 100 + i * 20, "y": 200 + i * 15, "t": i * 30} for i in range(15)]
    traj2 = [{"x": 100 + i * 20, "y": 200 + i * 15, "t": i * 30} for i in range(15)]
    
    sim_identical = compute_trajectory_similarity(traj1, traj2)
    assert sim_identical >= 0.95

    traj_different = [{"x": 800 - i * 10, "y": 100 + i * 40, "t": i * 30} for i in range(15)]
    sim_diff = compute_trajectory_similarity(traj1, traj_different)
    assert sim_diff < 0.70
