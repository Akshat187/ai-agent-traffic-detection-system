"""
Comprehensive Feature Extraction Pipeline for WebSense — v1.2.0

Translates raw multivariant telemetry into unified numerical behavioral feature vectors.

Feature Groups:
  1. Mouse Kinematics      — trajectory, velocity, acceleration, micro-corrections
  2. Keyboard Timing       — interval CV, hold duration (NO character content)
  3. Scroll Dynamics       — velocity, jump patterns, burst behavior
  4. Interaction Rhythm    — task pacing, first-action delay, click intervals
  5. Agency Profile        — planning pauses, nav segments, adaptation, diversity
  6. Environment Signals   — browser flags (supporting evidence only)
"""

import math
from typing import List, Dict, Any
from packages.core.kinematics import calculate_kinematics


def extract_keyboard_features(keyboard_events: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Extracts privacy-safe keyboard timing dynamics.
    Note: NO text or character contents are ever inspected or processed.
    """
    if not keyboard_events:
        return {
            "key_event_count": 0,
            "key_mean_latency": 0.0,
            "key_latency_std": 0.0,
            "key_latency_cv": 0.0,
            "key_mean_hold_time": 0.0,
            "key_hold_time_std": 0.0,
            "key_paste_count": 0,
            "key_burst_count": 0,
            "key_uniformity_score": 0.0
        }

    intervals = []
    holds = []
    pastes = 0
    bursts = 0

    for ev in keyboard_events:
        if ev.get("is_paste", False):
            pastes += 1
        inv = float(ev.get("interval", 0.0))
        hld = float(ev.get("hold", 0.0))
        if inv > 0:
            intervals.append(inv)
            if inv > 1000.0:  # Pause between typing bursts
                bursts += 1
        if hld > 0:
            holds.append(hld)

    def stats(arr):
        if not arr:
            return 0.0, 0.0
        m = sum(arr) / len(arr)
        v = sum((x - m) ** 2 for x in arr) / len(arr)
        return m, math.sqrt(v)

    mean_int, std_int = stats(intervals)
    mean_hld, std_hld = stats(holds)
    
    # Coefficient of variation (CV = std / mean). Bots often have near-0 CV (<0.05) or rigid intervals.
    latency_cv = (std_int / mean_int) if mean_int > 0 else 0.0

    # Uniformity score (0 = high human variance, 1 = perfectly robotic uniform keystrokes)
    uniformity = 1.0 / (1.0 + std_int) if intervals else 0.0

    return {
        "key_event_count": len(keyboard_events),
        "key_mean_latency": round(mean_int, 2),
        "key_latency_std": round(std_int, 2),
        "key_latency_cv": round(latency_cv, 4),
        "key_mean_hold_time": round(mean_hld, 2),
        "key_hold_time_std": round(std_hld, 2),
        "key_paste_count": pastes,
        "key_burst_count": bursts,
        "key_uniformity_score": round(uniformity, 4)
    }


def extract_scroll_features(scroll_events: List[Dict[str, Any]]) -> Dict[str, float]:
    """Extracts scrolling motion velocity, burstiness, and discrete jump patterns."""
    if not scroll_events or len(scroll_events) < 2:
        return {
            "scroll_event_count": len(scroll_events) if scroll_events else 0,
            "scroll_total_distance": 0.0,
            "scroll_velocity_mean": 0.0,
            "scroll_velocity_std": 0.0,
            "scroll_direction_changes": 0,
            "scroll_discrete_jump_ratio": 0.0,
            "scroll_burst_count": 0
        }

    deltas = []
    velocities = []
    dir_changes = 0
    discrete_jumps = 0
    bursts = 0
    total_dist = 0.0

    for i in range(1, len(scroll_events)):
        prev = scroll_events[i - 1]
        curr = scroll_events[i]
        dt = max(1.0, float(curr.get("t", 0) - prev.get("t", 0)))
        dy = float(curr.get("scroll_y", 0) - prev.get("scroll_y", 0))
        abs_dy = abs(dy)
        total_dist += abs_dy
        deltas.append(abs_dy)

        vel = (abs_dy / dt) * 1000.0
        velocities.append(vel)

        # Direction flip
        if i > 1:
            prev_dy = float(prev.get("scroll_y", 0) - scroll_events[i - 2].get("scroll_y", 0))
            if (dy * prev_dy) < 0:
                dir_changes += 1

        # Discrete jump (e.g. scrollTo instant teleport > 300px in single step)
        if abs_dy > 300 and dt < 30:
            discrete_jumps += 1
        if dt > 800:
            bursts += 1

    mean_v = sum(velocities) / len(velocities) if velocities else 0.0
    var_v = sum((x - mean_v) ** 2 for x in velocities) / len(velocities) if velocities else 0.0
    std_v = math.sqrt(var_v)
    jump_ratio = (discrete_jumps / len(scroll_events)) if scroll_events else 0.0

    return {
        "scroll_event_count": len(scroll_events),
        "scroll_total_distance": round(total_dist, 2),
        "scroll_velocity_mean": round(mean_v, 2),
        "scroll_velocity_std": round(std_v, 2),
        "scroll_direction_changes": dir_changes,
        "scroll_discrete_jump_ratio": round(jump_ratio, 4),
        "scroll_burst_count": bursts
    }


def extract_interaction_features(
    start_time: float,
    end_time: float,
    click_events: List[Dict[str, Any]],
    task_actions: List[Dict[str, Any]],
    mouse_events: List[Dict[str, Any]],
    keyboard_events: List[Dict[str, Any]]
) -> Dict[str, float]:
    """Extracts overall task pacing, cognitive latency, and interaction rhythm."""
    duration_ms = max(100.0, float(end_time - start_time)) if end_time >= start_time else 1000.0
    
    # First action delay (time from page load until first interaction)
    first_timestamps = []
    if mouse_events:
        first_timestamps.append(mouse_events[0].get("t", 0))
    if keyboard_events:
        first_timestamps.append(keyboard_events[0].get("t", 0))
    if click_events:
        first_timestamps.append(click_events[0].get("t", 0))
    if task_actions:
        first_timestamps.append(task_actions[0].get("t", 0))

    first_action_delay = min(first_timestamps) if first_timestamps else 0.0

    # Click interval variance
    click_intervals = []
    for i in range(1, len(click_events)):
        dt = float(click_events[i].get("t", 0) - click_events[i - 1].get("t", 0))
        if dt > 0:
            click_intervals.append(dt)

    mean_click_inv = sum(click_intervals) / len(click_intervals) if click_intervals else 0.0
    var_click_inv = sum((x - mean_click_inv) ** 2 for x in click_intervals) / len(click_intervals) if click_intervals else 0.0
    std_click_inv = math.sqrt(var_click_inv)

    total_events = (
        len(mouse_events) +
        len(keyboard_events) +
        len(click_events) +
        len(task_actions)
    )
    interaction_density = (total_events / (duration_ms / 1000.0)) if duration_ms > 0 else 0.0

    return {
        "duration_ms": round(duration_ms, 2),
        "first_action_delay_ms": round(first_action_delay, 2),
        "click_count": len(click_events),
        "click_mean_interval": round(mean_click_inv, 2),
        "click_interval_std": round(std_click_inv, 2),
        "task_action_count": len(task_actions),
        "total_event_count": total_events,
        "interaction_density": round(interaction_density, 2)
    }


def extract_agency_profile_features(
    task_actions: List[Dict[str, Any]],
    mouse_events: List[Dict[str, Any]],
    duration_ms: float,
) -> Dict[str, float]:
    """
    Extracts observable behavioral signals that may indicate autonomous decision-making.

    These are treated as evidence, not proof. Sophisticated human actors may produce
    similar signals, and sophisticated agents may suppress them.

    Agency Profile Features:
      - planning_pause_ratio: fraction of session time in pauses > 800ms (deliberation)
      - nav_segment_count: number of distinct linear path segments (segmented navigation)
      - action_interval_variance: variance between consecutive task action timestamps
      - adaptation_score: ratio of actions after major pauses (context-dependent selection)
      - interaction_diversity_score: entropy of interaction type usage
    """
    PLANNING_PAUSE_THRESHOLD_MS = 800.0

    # -- Action intervals from task_actions (primary bot-vs-agent signal) ---------------
    # LLM-driven agents have 1-5 s gaps between consecutive actions (model inference wait).
    # Scripted bots have gaps < 100 ms.  Humans have irregular, longer gaps.
    action_intervals = []
    action_interval_mean_ms = 0.0
    task_pause_end_times = []
    if len(task_actions) >= 2:
        for i in range(1, len(task_actions)):
            raw_t_curr = task_actions[i].get("t", 0)
            raw_t_prev = task_actions[i - 1].get("t", 0)
            dt = float(raw_t_curr) - float(raw_t_prev)
            if dt > 0:
                action_intervals.append(dt)
                if dt > PLANNING_PAUSE_THRESHOLD_MS:
                    task_pause_end_times.append(float(raw_t_curr))

    if action_intervals:
        action_interval_mean_ms = round(
            sum(action_intervals) / len(action_intervals), 2
        )
        mean_ai = action_interval_mean_ms
        var_ai = (
            sum((x - mean_ai) ** 2 for x in action_intervals) / len(action_intervals)
        )
        action_interval_variance = round(math.sqrt(var_ai), 2)
    else:
        action_interval_variance = 0.0

    # -- Planning pause ratio -----------------------------------------------------------
    # Fraction of session time in pauses > 800 ms.
    # Combines mouse-movement gaps AND task_action inference delays.
    planning_pause_ms = 0.0
    mouse_pause_end_times = []
    if len(mouse_events) >= 2:
        for i in range(1, len(mouse_events)):
            dt = float(mouse_events[i].get("t", 0)) - float(mouse_events[i - 1].get("t", 0))
            if dt > PLANNING_PAUSE_THRESHOLD_MS:
                planning_pause_ms += dt
                mouse_pause_end_times.append(float(mouse_events[i].get("t", 0)))

    for dt in action_intervals:
        if dt > PLANNING_PAUSE_THRESHOLD_MS:
            planning_pause_ms += dt

    planning_pause_ratio = (
        (planning_pause_ms / duration_ms) if duration_ms > 0 else 0.0
    )
    planning_pause_ratio = round(min(1.0, planning_pause_ratio), 4)

    # -- Navigation segment count -------------------------------------------------------
    # Distinct cursor segments separated by pauses > 400 ms.
    # High count + moderate straightness = agentic hallmark.
    nav_segments = 0
    if len(mouse_events) >= 4:
        segment_pause_threshold = 400.0
        in_segment = False
        for i in range(1, len(mouse_events)):
            dt = (
                float(mouse_events[i].get("t", 0))
                - float(mouse_events[i - 1].get("t", 0))
            )
            if dt > segment_pause_threshold:
                if in_segment:
                    nav_segments += 1
                in_segment = False
            else:
                in_segment = True
        if in_segment:
            nav_segments += 1

    # -- Adaptation score --------------------------------------------------------------
    # Ratio of task actions that occur within 3 s after a planning pause.
    # Higher = more context-sensitive action selection (agentic indicator).
    all_pause_end_times = mouse_pause_end_times + task_pause_end_times
    actions_after_pause = 0
    if task_actions and all_pause_end_times:
        action_times = [float(a.get("t", 0)) for a in task_actions]
        for at in action_times:
            for pet in all_pause_end_times:
                if 0 <= (at - pet) <= 3000:
                    actions_after_pause += 1
                    break

    adaptation_score = round(
        (actions_after_pause / len(task_actions)) if task_actions else 0.0,
        4,
    )

    # -- Interaction diversity score ---------------------------------------------------
    # Shannon entropy of interaction-type usage (mouse, task).
    # Higher diversity = more human-like or agentic; zero = narrow automation.
    type_counts = {"mouse": len(mouse_events), "task": len(task_actions)}
    total = sum(type_counts.values())
    if total > 0:
        entropy = 0.0
        for count in type_counts.values():
            if count > 0:
                p = count / total
                entropy -= p * math.log2(p)
        max_entropy = math.log2(len(type_counts))
        interaction_diversity_score = round(
            entropy / max_entropy if max_entropy > 0 else 0.0, 4
        )
    else:
        interaction_diversity_score = 0.0

    return {
        "planning_pause_ratio": planning_pause_ratio,
        "nav_segment_count": nav_segments,
        "action_interval_variance": action_interval_variance,
        "action_interval_mean_ms": action_interval_mean_ms,
        "adaptation_score": adaptation_score,
        "interaction_diversity_score": interaction_diversity_score,
    }


def extract_all_features(session_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Master feature extraction pipeline — v1.2.0.

    Combines:
      - Mouse kinematics (velocity, jerk, straightness, micro-corrections)
      - Keyboard timing dynamics (interval CV, hold durations — NO character content)
      - Scroll dynamics (velocity, jump patterns)
      - Interaction rhythm (pacing, first-action delay)
      - Agency profile signals (planning pauses, nav segments, adaptation)
      - Browser environment signals (supporting evidence only)
    """
    mouse_evs = session_data.get("mouse_events", [])
    kb_evs = session_data.get("keyboard_events", [])
    scroll_evs = session_data.get("scroll_events", [])
    click_evs = session_data.get("click_events", [])
    task_acts = session_data.get("task_actions", [])
    browser = session_data.get("browser_signals", {})
    start_t = float(session_data.get("start_time", 0.0))
    end_t = float(session_data.get("end_time", start_t + session_data.get("duration_ms", 1000.0)))

    # Normalize timestamps: detect if values are Unix seconds (1e9..2e10 range) vs milliseconds.
    # Seed data sends ms (~1.7e12), extension now also sends ms.
    # Guard against legacy payloads that may still send seconds.
    _MS_THRESHOLD = 1e10  # If timestamp > 10 billion, it's already in ms (Unix ms epoch)
    if 0 < start_t < _MS_THRESHOLD and 0 < end_t < _MS_THRESHOLD:
        # Looks like Unix seconds — convert to ms for consistent duration computation
        start_t *= 1000.0
        end_t *= 1000.0

    # Use payload's explicit duration_ms if timestamps are unreliable (e.g. relative t=0)
    payload_duration = session_data.get("duration_ms")
    if payload_duration and float(payload_duration) > 0:
        duration_ms = max(100.0, float(payload_duration))
    elif end_t >= start_t and end_t > 0:
        duration_ms = max(100.0, float(end_t - start_t))
    else:
        duration_ms = 1000.0

    # --- Effective duration for ratio features -----------------------------------
    # Prefer active_duration_ms (bounded engagement window, excludes idle gaps).
    # If the client is an older version that doesn't send it, fall back to raw
    # duration_ms capped at 10 minutes so one idle-open tab can't silently
    # collapse planning_pause_ratio and interaction_density toward zero.
    MAX_EFFECTIVE_DURATION_MS = 600_000.0  # 10 minutes
    raw_active = session_data.get("active_duration_ms")
    if raw_active is not None and float(raw_active) > 0:
        effective_duration_ms = max(100.0, float(raw_active))
    else:
        # Older client: cap raw tab-lifetime duration at 10 min
        effective_duration_ms = max(100.0, min(duration_ms, MAX_EFFECTIVE_DURATION_MS))

    kinematics = calculate_kinematics(mouse_evs)
    keyboard = extract_keyboard_features(kb_evs)
    scroll = extract_scroll_features(scroll_evs)
    interaction = extract_interaction_features(start_t, end_t, click_evs, task_acts, mouse_evs, kb_evs)
    agency = extract_agency_profile_features(task_acts, mouse_evs, effective_duration_ms)

    # Environment signals — lowest weight, supporting evidence only
    webdriver = bool(browser.get("webdriver", False))
    touch = bool(browser.get("touch_support", False))
    hardware_threads = int(browser.get("hardware_concurrency", 4) or 4)

    features = {
        **kinematics,
        **keyboard,
        **scroll,
        **interaction,
        **agency,
        # Environmental signals (supporting evidence — not primary classifiers)
        "webdriver_flag": 1.0 if webdriver else 0.0,
        "touch_support": 1.0 if touch else 0.0,
        "hardware_concurrency": float(hardware_threads),
        # Expose both durations for dashboard display and diagnostics
        "active_duration_ms": round(effective_duration_ms, 2),
        # Override duration_ms in features dict with effective value so rules.py
        # reads the correct bounded duration for dwell-time checks.
        "duration_ms": round(effective_duration_ms, 2),
    }

    return features

