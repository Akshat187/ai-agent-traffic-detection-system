"""
Dynamic Time Warping (DTW) and Trajectory Normalization Module.
Used by Layer 4 (Replay Analysis) to detect exact or near-exact mouse path replications.
"""

import math
from typing import List, Dict, Any, Tuple


def normalize_and_resample_trajectory(
    events: List[Dict[str, Any]],
    num_points: int = 50
) -> List[Tuple[float, float]]:
    """
    Normalizes a mouse trajectory into [0, 1] x [0, 1] coordinate space
    and resamples it along the path to equidistant points.
    """
    if not events or len(events) < 2:
        return [(0.0, 0.0)] * num_points

    coords = [(float(e["x"]), float(e["y"])) for e in events]
    
    # 1. Bounding box normalization
    min_x = min(p[0] for p in coords)
    max_x = max(p[0] for p in coords)
    min_y = min(p[1] for p in coords)
    max_y = max(p[1] for p in coords)
    
    range_x = max(1.0, max_x - min_x)
    range_y = max(1.0, max_y - min_y)
    
    norm_coords = [((p[0] - min_x) / range_x, (p[1] - min_y) / range_y) for p in coords]

    # 2. Compute cumulative path length
    cum_dist = [0.0]
    for i in range(1, len(norm_coords)):
        dx = norm_coords[i][0] - norm_coords[i - 1][0]
        dy = norm_coords[i][1] - norm_coords[i - 1][1]
        dist = math.sqrt(dx * dx + dy * dy)
        cum_dist.append(cum_dist[-1] + dist)

    total_len = cum_dist[-1]
    if total_len == 0:
        return [norm_coords[0]] * num_points

    # 3. Equidistant resampling
    resampled = [norm_coords[0]]
    step = total_len / float(num_points - 1)
    
    for k in range(1, num_points - 1):
        target_dist = k * step
        # Find segment containing target_dist
        idx = 0
        while idx < len(cum_dist) - 1 and cum_dist[idx + 1] < target_dist:
            idx += 1
        
        seg_start = cum_dist[idx]
        seg_end = cum_dist[idx + 1]
        seg_len = max(1e-6, seg_end - seg_start)
        ratio = (target_dist - seg_start) / seg_len
        
        rx = norm_coords[idx][0] + ratio * (norm_coords[idx + 1][0] - norm_coords[idx][0])
        ry = norm_coords[idx][1] + ratio * (norm_coords[idx + 1][1] - norm_coords[idx][1])
        resampled.append((rx, ry))

    resampled.append(norm_coords[-1])
    return resampled


def fast_dtw_distance(
    seq1: List[Tuple[float, float]],
    seq2: List[Tuple[float, float]],
    window_size: int = 10
) -> float:
    """
    Computes DTW distance between two 2D resampled sequences with Sakoe-Chiba band.
    """
    n, m = len(seq1), len(seq2)
    if n == 0 or m == 0:
        return 999.0

    w = max(window_size, abs(n - m))
    
    # Initialize DP matrix with infinity
    dtw_matrix = {}
    for i in range(-1, n):
        for j in range(-1, m):
            dtw_matrix[(i, j)] = float("inf")
    dtw_matrix[(-1, -1)] = 0.0

    for i in range(n):
        j_start = max(0, i - w)
        j_end = min(m, i + w + 1)
        for j in range(j_start, j_end):
            dx = seq1[i][0] - seq2[j][0]
            dy = seq1[i][1] - seq2[j][1]
            cost = math.sqrt(dx * dx + dy * dy)
            
            dtw_matrix[(i, j)] = cost + min(
                dtw_matrix[(i - 1, j)],      # insertion
                dtw_matrix[(i, j - 1)],      # deletion
                dtw_matrix[(i - 1, j - 1)]   # match
            )

    raw_dist = dtw_matrix.get((n - 1, m - 1), float("inf"))
    # Normalize by path length
    normalized_dist = raw_dist / float(n + m)
    return normalized_dist


def compute_trajectory_similarity(
    events1: List[Dict[str, Any]],
    events2: List[Dict[str, Any]],
    num_points: int = 40
) -> float:
    """
    Returns similarity score between 0.0 and 1.0.
    1.0 = identical trajectory (High confidence replay).
    <0.7 = natural variation between different human visits.
    """
    if not events1 or not events2 or len(events1) < 2 or len(events2) < 2:
        return 0.0

    p1_start = (float(events1[0].get("x", 0)), float(events1[0].get("y", 0)))
    p1_end = (float(events1[-1].get("x", 0)), float(events1[-1].get("y", 0)))
    p2_start = (float(events2[0].get("x", 0)), float(events2[0].get("y", 0)))
    p2_end = (float(events2[-1].get("x", 0)), float(events2[-1].get("y", 0)))

    start_dist = math.sqrt((p1_start[0] - p2_start[0]) ** 2 + (p1_start[1] - p2_start[1]) ** 2)
    end_dist = math.sqrt((p1_end[0] - p2_end[0]) ** 2 + (p1_end[1] - p2_end[1]) ** 2)

    res1 = normalize_and_resample_trajectory(events1, num_points)
    res2 = normalize_and_resample_trajectory(events2, num_points)
    
    dtw_dist = fast_dtw_distance(res1, res2, window_size=8)
    
    # Shape similarity with steep decay
    shape_sim = math.exp(-8.0 * dtw_dist)
    # Spatial anchor similarity (decay if start/end endpoints don't match)
    anchor_sim = math.exp(-(start_dist + end_dist) / 120.0)

    combined_sim = shape_sim * (0.35 + 0.65 * anchor_sim)
    return round(combined_sim, 4)

