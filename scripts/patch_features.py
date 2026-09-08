"""
Patch script: replaces extract_agency_profile_features body in features.py
with the enhanced version that extracts planning pauses from task_actions.
"""
import pathlib

path = pathlib.Path(
    r"d:\RealDevSquad\akshat-projects\ai_agent traffic detection system"
    r"\packages\core\features.py"
)
src = path.read_text(encoding="utf-8-sig")

marker_start = "    PLANNING_PAUSE_THRESHOLD_MS = 800.0\n"
marker_end = "\n\n\ndef extract_all_features"

start_idx = src.index(marker_start)
end_idx = src.index(marker_end, start_idx)

NEW_BODY = '''    PLANNING_PAUSE_THRESHOLD_MS = 800.0

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
    }'''

new_src = src[:start_idx] + NEW_BODY + src[end_idx:]
path.write_text(new_src, encoding="utf-8")
print(f"Patched. New line count: {len(new_src.splitlines())}")
