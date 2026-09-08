"""
Kinematics and Motion Dynamics Calculation Engine for WebSense.
Computes high-resolution physical motion metrics from 2D mouse trajectory data.
"""

import math
from typing import List, Dict, Any, Tuple


def compute_distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Euclidean distance between two 2D points."""
    return math.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2)


def compute_angle(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Direction angle in radians from p1 to p2."""
    return math.atan2(p2[1] - p1[1], p2[0] - p1[0])


def angle_diff(a1: float, a2: float) -> float:
    """Absolute angular difference wrapped to [0, pi]."""
    diff = abs(a1 - a2) % (2 * math.pi)
    if diff > math.pi:
        diff = 2 * math.pi - diff
    return diff


def calculate_kinematics(mouse_events: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Extracts deep kinematic motion features from raw mouse events.
    Events format: [{'x': float, 'y': float, 't': float, 'type': str}, ...]
    """
    if not mouse_events or len(mouse_events) < 2:
        return {
            "mouse_event_count": len(mouse_events) if mouse_events else 0,
            "path_length": 0.0,
            "direct_distance": 0.0,
            "straightness_ratio": 1.0,
            "mean_velocity": 0.0,
            "velocity_std": 0.0,
            "max_velocity": 0.0,
            "mean_acceleration": 0.0,
            "acceleration_std": 0.0,
            "jerk_mean": 0.0,
            "jerk_std": 0.0,
            "direction_changes": 0,
            "micro_corrections": 0,
            "pause_count": 0,
            "pause_time_ratio": 0.0,
            "low_speed_ratio": 0.0,
            "curvature_mean": 0.0,
            "angular_velocity_mean": 0.0
        }

    # Filter distinct temporal points
    cleaned_events = [mouse_events[0]]
    for ev in mouse_events[1:]:
        if ev["t"] > cleaned_events[-1]["t"] or (ev["x"] != cleaned_events[-1]["x"] or ev["y"] != cleaned_events[-1]["y"]):
            cleaned_events.append(ev)

    n = len(cleaned_events)
    if n < 2:
        return {
            "mouse_event_count": n,
            "path_length": 0.0,
            "direct_distance": 0.0,
            "straightness_ratio": 1.0,
            "mean_velocity": 0.0,
            "velocity_std": 0.0,
            "max_velocity": 0.0,
            "mean_acceleration": 0.0,
            "acceleration_std": 0.0,
            "jerk_mean": 0.0,
            "jerk_std": 0.0,
            "direction_changes": 0,
            "micro_corrections": 0,
            "pause_count": 0,
            "pause_time_ratio": 0.0,
            "low_speed_ratio": 0.0,
            "curvature_mean": 0.0,
            "angular_velocity_mean": 0.0
        }

    # 1. Trajectory segments
    distances = []
    dt_list = []
    velocities = []
    angles = []
    path_length = 0.0

    for i in range(1, n):
        p_prev = (cleaned_events[i - 1]["x"], cleaned_events[i - 1]["y"])
        p_curr = (cleaned_events[i]["x"], cleaned_events[i]["y"])
        dist = compute_distance(p_prev, p_curr)
        dt = max(1.0, float(cleaned_events[i]["t"] - cleaned_events[i - 1]["t"]))  # ms
        
        path_length += dist
        distances.append(dist)
        dt_list.append(dt)
        vel = (dist / dt) * 1000.0  # px / sec
        velocities.append(vel)
        angles.append(compute_angle(p_prev, p_curr))

    direct_distance = compute_distance(
        (cleaned_events[0]["x"], cleaned_events[0]["y"]),
        (cleaned_events[-1]["x"], cleaned_events[-1]["y"])
    )
    
    # Straightness ratio (0 to 1; 1 = perfectly straight robot line, <0.75 = natural curved human trajectory)
    straightness_ratio = (direct_distance / path_length) if path_length > 0 else 1.0
    straightness_ratio = min(1.0, max(0.0, straightness_ratio))

    # 2. Accelerations (d_vel / dt)
    accelerations = []
    for i in range(1, len(velocities)):
        dv = velocities[i] - velocities[i - 1]
        dt = (dt_list[i] + dt_list[i - 1]) / 2.0
        acc = (dv / max(1.0, dt)) * 1000.0  # px / sec^2
        accelerations.append(acc)

    # 3. Jerk (d_acc / dt)
    jerks = []
    for i in range(1, len(accelerations)):
        da = accelerations[i] - accelerations[i - 1]
        dt = dt_list[i]
        jerk = (da / max(1.0, dt)) * 1000.0  # px / sec^3
        jerks.append(abs(jerk))

    # 4. Direction changes & micro-corrections
    direction_changes = 0
    micro_corrections = 0
    angle_diffs = []

    for i in range(1, len(angles)):
        ad = angle_diff(angles[i], angles[i - 1])
        angle_diffs.append(ad)
        # Direction change threshold (> 45 deg)
        if ad > (math.pi / 4.0):
            direction_changes += 1
        # Micro-correction: small sharp angle jitter (between 15 deg and 90 deg with small distance)
        if (math.pi / 12.0) <= ad <= (math.pi / 2.0) and distances[i] < 35:
            micro_corrections += 1

    # 5. Pauses and Low-Speed Analysis
    total_time = sum(dt_list)
    pause_time = 0.0
    pause_count = 0
    low_speed_time = 0.0

    for i, vel in enumerate(velocities):
        dt = dt_list[i]
        if vel < 10.0:  # nearly still
            pause_time += dt
            if dt > 150.0:
                pause_count += 1
        elif vel < 100.0:  # low speed fine movement
            low_speed_time += dt

    pause_time_ratio = (pause_time / total_time) if total_time > 0 else 0.0
    low_speed_ratio = (low_speed_time / total_time) if total_time > 0 else 0.0

    # Summary statistics helper
    def mean_std(arr):
        if not arr:
            return 0.0, 0.0
        m = sum(arr) / len(arr)
        variance = sum((x - m) ** 2 for x in arr) / len(arr)
        return m, math.sqrt(variance)

    mean_vel, std_vel = mean_std(velocities)
    mean_acc, std_acc = mean_std([abs(a) for a in accelerations])
    mean_jerk, std_jerk = mean_std(jerks)
    mean_curv, _ = mean_std(angle_diffs)

    return {
        "mouse_event_count": n,
        "path_length": round(path_length, 2),
        "direct_distance": round(direct_distance, 2),
        "straightness_ratio": round(straightness_ratio, 4),
        "mean_velocity": round(mean_vel, 2),
        "velocity_std": round(std_vel, 2),
        "max_velocity": round(max(velocities) if velocities else 0.0, 2),
        "mean_acceleration": round(mean_acc, 2),
        "acceleration_std": round(std_acc, 2),
        "jerk_mean": round(mean_jerk, 2),
        "jerk_std": round(std_jerk, 2),
        "direction_changes": direction_changes,
        "micro_corrections": micro_corrections,
        "pause_count": pause_count,
        "pause_time_ratio": round(pause_time_ratio, 4),
        "low_speed_ratio": round(low_speed_ratio, 4),
        "curvature_mean": round(mean_curv, 4),
        "angular_velocity_mean": round(mean_curv / (total_time / 1000.0), 4) if total_time > 0 else 0.0
    }

