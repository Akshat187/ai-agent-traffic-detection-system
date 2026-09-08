"""
Synthetic Ground-Truth Dataset Generator for WebSense — v1.1

Generates physically-grounded behavioral sessions for three agent classes:
  - HUMAN: organic Bézier curves, variable typing, natural pauses
  - BOT: several subtypes (deterministic, randomized, evasive) with different webdriver strategies
  - AI_AGENT: segmented deliberate motion, uniform-ish typing, labelled as simulated

FIXES from v1.0:
  - BOT webdriver flag is now stochastic (evasive bots have webdriver=False)
  - AI_AGENT webdriver flag is stochastic (non-headless agents won't have it True)
  - Task-action names are now TASK-AGNOSTIC to prevent task→class leakage
  - Action names are drawn from a shared vocabulary across all classes
  - Human behavioral variation is wider (more realistic inter-person variance)
  - All sessions carry data_source label for dashboard demarcation
"""

import math
import random
import time
from typing import List, Dict, Any, Optional


# ─── Shared Action Vocabulary ─────────────────────────────────────────────────
# Task-agnostic action names used across ALL classes and ALL tasks.
# This prevents the model from learning task→class correlations.
SHARED_ACTIONS = {
    "shopping": ["browsed_listing", "filter_applied", "item_selected", "quantity_updated", "checkout_initiated"],
    "travel":   ["browsed_listing", "filter_applied", "item_selected", "quantity_updated", "checkout_initiated"],
    "forum":    ["browsed_listing", "filter_applied", "item_selected", "quantity_updated", "checkout_initiated"],
}


# ─── Mouse Path Generators ────────────────────────────────────────────────────

def generate_human_mouse_path(
    start_x: int, start_y: int,
    end_x:   int, end_y:   int,
    duration_ms: int,
    rng: Optional[random.Random] = None,
) -> List[Dict[str, Any]]:
    """
    Organic human-like Bézier trajectory with:
    - Ease-in/ease-out temporal warping
    - Gaussian micro-corrections (physiological hand tremor)
    - Random overshoots and self-corrections near target
    """
    if rng is None:
        rng = random
    events = []
    steps = max(15, int(duration_ms / 25))

    # Two random control points
    ctrl1_x = start_x + (end_x - start_x) * rng.uniform(0.15, 0.45) + rng.gauss(0, 55)
    ctrl1_y = start_y + (end_y - start_y) * rng.uniform(0.15, 0.45) + rng.gauss(0, 55)
    ctrl2_x = start_x + (end_x - start_x) * rng.uniform(0.55, 0.85) + rng.gauss(0, 55)
    ctrl2_y = start_y + (end_y - start_y) * rng.uniform(0.55, 0.85) + rng.gauss(0, 55)

    for i in range(steps + 1):
        t = i / float(steps)
        # Ease-in/ease-out temporal warping
        t_warped = (math.sin((t - 0.5) * math.pi) + 1.0) / 2.0

        # Cubic Bézier
        bx = ((1-t)**3 * start_x + 3*(1-t)**2 * t * ctrl1_x
              + 3*(1-t) * t**2 * ctrl2_x + t**3 * end_x)
        by = ((1-t)**3 * start_y + 3*(1-t)**2 * t * ctrl1_y
              + 3*(1-t) * t**2 * ctrl2_y + t**3 * end_y)

        # Physiological jitter — stronger in mid-path
        jitter_scale = 2.0 if 0.1 < t < 0.9 else 0.6
        jitter_x = rng.gauss(0, jitter_scale)
        jitter_y = rng.gauss(0, jitter_scale)

        events.append({
            "x":    round(bx + jitter_x),
            "y":    round(by + jitter_y),
            "t":    round(t_warped * duration_ms),
            "type": "move",
        })
    return events


def generate_bot_mouse_path(
    start_x: int, start_y: int,
    end_x:   int, end_y:   int,
    duration_ms: int,
    jitter_sigma: float = 0.0,
    rng: Optional[random.Random] = None,
) -> List[Dict[str, Any]]:
    """
    Robotic linear trajectory.
    jitter_sigma=0.0 → deterministic (Playwright default).
    jitter_sigma>0.0 → randomized/evasive bots adding Gaussian noise.
    """
    if rng is None:
        rng = random
    events = []
    steps = max(5, int(duration_ms / 30))
    for i in range(steps + 1):
        t = i / float(steps)
        noise_x = rng.gauss(0, jitter_sigma) if jitter_sigma > 0 else 0.0
        noise_y = rng.gauss(0, jitter_sigma) if jitter_sigma > 0 else 0.0
        events.append({
            "x":    round(start_x + t * (end_x - start_x) + noise_x),
            "y":    round(start_y + t * (end_y - start_y) + noise_y),
            "t":    round(t * duration_ms),
            "type": "move",
        })
    return events


def generate_agent_mouse_path(
    waypoints: List[tuple],
    duration_ms: int,
    rng: Optional[random.Random] = None,
) -> List[Dict[str, Any]]:
    """
    Segmented linear motion with deliberate planning pauses.
    Characteristic of autonomous AI agents: each DOM target is approached
    separately with a deliberation gap before each move.
    """
    if rng is None:
        rng = random
    events = []
    cur_t = 0
    seg_time = int(duration_ms / max(1, len(waypoints) - 1))

    for i in range(len(waypoints) - 1):
        p1 = waypoints[i]
        p2 = waypoints[i + 1]
        steps = rng.randint(6, 10)
        move_fraction = rng.uniform(0.60, 0.80)   # proportion of seg_time spent moving

        for j in range(steps + 1):
            t = j / float(steps)
            events.append({
                "x":    round(p1[0] + t * (p2[0] - p1[0])),
                "y":    round(p1[1] + t * (p2[1] - p1[1])),
                "t":    round(cur_t + t * (seg_time * move_fraction)),
                "type": "move",
            })

        cur_t += seg_time    # includes both the move and the planning pause

    return events


# ─── Scroll Generators ────────────────────────────────────────────────────────

def generate_human_scroll(duration_ms: int, rng: Optional[random.Random] = None) -> List[Dict]:
    """Human scroll: variable speed, clusters of small increments."""
    if rng is None:
        rng = random
    events = []
    scroll_y = 0
    t = int(duration_ms * 0.1)
    while t < int(duration_ms * 0.9) and len(events) < 40:
        delta = rng.randint(30, 180)
        scroll_y += delta
        events.append({"t": t, "scroll_y": scroll_y, "delta_y": delta})
        t += rng.randint(150, 600)
    return events


def generate_bot_scroll(duration_ms: int, rng: Optional[random.Random] = None) -> List[Dict]:
    """Bot scroll: uniform large jumps (JavaScript window.scrollTo)."""
    if rng is None:
        rng = random
    events = []
    step_y = rng.randint(300, 500)   # large fixed steps
    scroll_y = 0
    t = int(duration_ms * 0.05)
    while t < int(duration_ms * 0.9) and len(events) < 10:
        scroll_y += step_y
        events.append({"t": t, "scroll_y": scroll_y, "delta_y": step_y})
        t += rng.randint(100, 200)   # very fast, uniform
    return events


def generate_agent_scroll(duration_ms: int, rng: Optional[random.Random] = None) -> List[Dict]:
    """Agent scroll: infrequent, deliberate, medium-sized jumps."""
    if rng is None:
        rng = random
    events = []
    scroll_y = 0
    t = int(duration_ms * 0.2)
    for _ in range(rng.randint(2, 5)):
        delta = rng.randint(200, 400)
        scroll_y += delta
        events.append({"t": t, "scroll_y": scroll_y, "delta_y": delta})
        t += rng.randint(800, 2000)
    return events


# ——— Session Generator ——————————————————————————————————————————————————————

def generate_synthetic_session(
    label: str,
    task: str = "shopping",
    index: int = 0,
    seed: Optional[int] = None,
    subtype: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generates a single physically grounded interaction session.

    Args:
        label: "HUMAN" | "TRADITIONAL_AUTOMATION" (or "BOT") | "AGENTIC_AI" (or "AI_AGENT")
        task:  "shopping" | "travel" | "forum"
            (controls which workflow actions appear, but NOT which behavioral signals)
        index: Session index for unique ID generation.
        seed:  Optional random seed for reproducibility.
        subtype: Optional subtype for the label (e.g. "deterministic", "randomized", "evasive" for bots).

    Returns:
        A dict matching IngestSessionRequest schema.
    """
    rng = random.Random(seed) if seed is not None else random.Random()

    # Validate task
    if task not in SHARED_ACTIONS:
        task = "shopping"

    # Use shared task-agnostic action names to avoid task→class leakage
    actions_vocab = SHARED_ACTIONS[task]

    label_upper = label.upper()
    if label_upper in ("TRADITIONAL_AUTOMATION", "BOT"):
        target_label = "TRADITIONAL_AUTOMATION"
    elif label_upper in ("AGENTIC_AI", "AI_AGENT"):
        target_label = "AGENTIC_AI"
    else:
        target_label = "HUMAN"

    # Base session ID includes unix timestamp for uniqueness
    ts = int(time.time())
    session_id = f"demo_{target_label.lower()}_{task}_{index:03d}_{ts}"
    visitor_id = f"vis_{target_label.lower()}_{index:03d}"

    # ——— HUMAN ————————————————————————————————————————————————————————————————
    if target_label == "HUMAN":
        # Wide duration range — humans vary enormously in pace.
        # Short sessions (3.5–6s) can look more bot-like — intentional class boundary noise.
        duration = rng.randint(3500, 18000)

        sx, sy = rng.randint(80, 350), rng.randint(80, 350)
        ex, ey = rng.randint(550, 1100), rng.randint(350, 750)
        mouse_events = generate_human_mouse_path(sx, sy, ex, ey, int(duration * 0.65), rng)

        # Variable typing — CV typically 0.3–0.6 for humans.
        # Some fast typists have lower CV that can overlap with bot range.
        keyboard_events = []
        cur_k_t = int(duration * rng.uniform(0.15, 0.25))
        # Occasional fast typist: very short intervals (some humans type at 120+ WPM)
        is_fast_typist = rng.random() < 0.15
        for _ in range(rng.randint(8, 22)):
            base_interval = rng.gauss(145 if is_fast_typist else 195, 55 if is_fast_typist else 68)
            cur_k_t += max(35, int(base_interval))
            keyboard_events.append({
                "t":        cur_k_t,
                "interval": max(35, round(base_interval, 1)),
                "hold":     rng.randint(35, 110),  # occasional very quick holds
                "is_paste": False,
            })

        scroll_events = generate_human_scroll(duration, rng)

        # Some humans click very close to target (smaller target radius)
        click_events = [
            {"x": rng.randint(ex - 25, ex + 25), "y": rng.randint(ey - 25, ey + 25),
             "t": int(duration * 0.70), "target_category": "button"},
        ]

        browser_signals = {
            "webdriver":           False,
            "screen_width":        rng.choice([1920, 1440, 1536, 1280]),
            "screen_height":       rng.choice([1080, 900, 864, 800]),
            "viewport_width":      rng.choice([1280, 1440, 1200]),
            "viewport_height":     rng.choice([720, 800, 680]),
            "device_pixel_ratio":  rng.choice([1.0, 1.25, 1.5, 2.0]),
            "touch_support":       False,
            "hardware_concurrency": rng.choice([4, 8, 12, 16]),
            "platform":            rng.choice(["Win32", "MacIntel", "Linux x86_64"]),
            "language":            "en-US",
            "user_agent":          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        task_actions = [
            {"action": actions_vocab[0], "t": int(duration * 0.15), "details": {}},
            {"action": actions_vocab[1], "t": int(duration * 0.40), "details": {}},
            {"action": actions_vocab[2], "t": int(duration * 0.65), "details": {}},
            {"action": actions_vocab[4], "t": int(duration * 0.88), "details": {}},
        ]
        data_source = "synthetic_human"

    # ——— BOT ——————————————————————————————————————————————————————————————————
    elif target_label == "TRADITIONAL_AUTOMATION":
        # Three bot subtypes with different evasion capabilities
        bot_subtype = subtype or rng.choice(["deterministic", "randomized", "evasive"])


        if bot_subtype == "deterministic":
            # Classic Playwright/Selenium: webdriver=True, zero jitter, very fast
            duration = rng.randint(300, 900)
            jitter_sigma = 0.0
            webdriver = True
            fixed_interval = rng.randint(35, 55)   # very uniform
            typing_variance = 2
        elif bot_subtype == "randomized":
            # Adds some Gaussian jitter to paths but still webdriver=True
            duration = rng.randint(600, 1800)
            jitter_sigma = rng.uniform(3.0, 8.0)
            webdriver = True
            fixed_interval = rng.randint(50, 100)
            typing_variance = 15
        else:  # evasive
            # Attempts to look more human: webdriver=False, larger jitter, slower.
            # jitter_sigma now wider (up to 22) so some evasive bot paths are nearly
            # indistinguishable from human Bézier paths — intentional boundary noise.
            duration = rng.randint(1200, 4500)
            jitter_sigma = rng.uniform(8.0, 22.0)
            webdriver = False    # evasive: hides webdriver flag
            fixed_interval = rng.randint(55, 140)
            typing_variance = 30

        mouse_events = generate_bot_mouse_path(
            200, 200, 800, 600, int(duration * 0.8), jitter_sigma, rng
        )

        # Robotic typing: low CV for deterministic/randomized; evasive bots
        # have some hold-time overlap with the human range to make detection harder.
        keyboard_events = []
        cur_k_t = 50
        for _ in range(rng.randint(8, 14)):
            inv = fixed_interval + rng.randint(-typing_variance, typing_variance)
            cur_k_t += max(20, inv)
            # Evasive bots inject longer occasional holds to mimic human finger release
            if bot_subtype == "evasive" and rng.random() < 0.25:
                hold = rng.randint(40, 65)   # bleeds into low end of human range (45-110)
            else:
                hold = rng.randint(15, 30)   # classic robotic hold
            keyboard_events.append({
                "t":        cur_k_t,
                "interval": max(20, inv),
                "hold":     hold,
                "is_paste": False,
            })

        scroll_events = generate_bot_scroll(duration, rng)

        click_events = [
            {"x": 800, "y": 600, "t": int(duration * 0.85), "target_category": "button"},
        ]

        browser_signals = {
            "webdriver":           webdriver,
            "screen_width":        1280,
            "screen_height":       800,
            "viewport_width":      1280,
            "viewport_height":     800,
            "device_pixel_ratio":  1.0,
            "touch_support":       False,
            "hardware_concurrency": 2,
            "platform":            "Linux x86_64",
            "language":            "en-US",
            "user_agent":          (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) HeadlessChrome/124.0.0.0 Safari/537.36"
                if webdriver else
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }

        task_actions = [
            {"action": actions_vocab[1], "t": int(duration * 0.35), "details": {}},
            {"action": actions_vocab[3], "t": int(duration * 0.60), "details": {}},
            {"action": actions_vocab[4], "t": int(duration * 0.80), "details": {}},
        ]
        data_source = "synthetic_automation"

    # ── AI_AGENT ──────────────────────────────────────────────────────────────
    else:
        # AI agent — explicitly SIMULATED.
        # Not always headless: modern agents can run in non-headless mode.
        duration = rng.randint(5000, 13000)

        # Stochastic webdriver: headless agents → True; non-headless agents → False
        webdriver = rng.random() < 0.60   # 60% headless, 40% non-headless

        waypoints = [
            (150, 200),
            (rng.randint(350, 550), rng.randint(200, 350)),
            (rng.randint(600, 800), rng.randint(400, 600)),
            (rng.randint(800, 1000), rng.randint(550, 700)),
        ]
        mouse_events = generate_agent_mouse_path(waypoints, int(duration * 0.70), rng)

        # Agent typing: narrower interval range than human, but not as uniform as bot.
        # Some agents have longer think-gaps between keystrokes (LLM latency).
        keyboard_events = []
        cur_k_t = int(duration * 0.25)
        # 25% of agents have a long initial planning delay before typing
        if rng.random() < 0.25:
            cur_k_t += rng.randint(800, 2200)
        for _ in range(rng.randint(5, 14)):
            # Occasional LLM latency spike between keystrokes
            if rng.random() < 0.15:
                inv = rng.randint(300, 900)   # think-gap
            else:
                inv = rng.randint(55, 145)    # normal agent keystroke pace
            cur_k_t += inv
            keyboard_events.append({
                "t":        cur_k_t,
                "interval": inv,
                "hold":     rng.randint(25, 55),  # slightly wider range
                "is_paste": False,
            })

        scroll_events = generate_agent_scroll(duration, rng)

        click_events = [
            {"x": waypoints[1][0], "y": waypoints[1][1],
             "t": int(duration * 0.35), "target_category": "input"},
            {"x": waypoints[-1][0], "y": waypoints[-1][1],
             "t": int(duration * 0.80), "target_category": "button"},
        ]

        browser_signals = {
            "webdriver":           webdriver,
            "screen_width":        1920,
            "screen_height":       1080,
            "viewport_width":      1280,
            "viewport_height":     800,
            "device_pixel_ratio":  1.0,
            "touch_support":       False,
            "hardware_concurrency": rng.choice([4, 8]),
            "platform":            "Win32",
            "language":            "en-US",
            "user_agent":          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        }

        task_actions = [
            {"action": actions_vocab[0], "t": int(duration * 0.20), "details": {}},
            {"action": actions_vocab[2], "t": int(duration * 0.50), "details": {}},
            {"action": actions_vocab[3], "t": int(duration * 0.75), "details": {}},
            {"action": actions_vocab[4], "t": int(duration * 0.90), "details": {}},
        ]
        data_source = "synthetic_simulated_agent"

    base_ts = 1724900000000 + (index * 60000)
    return {
        "session_id":          session_id,
        "visitor_id":          visitor_id,
        "task":                task,
        "start_time":          base_ts,
        "end_time":            base_ts + duration,
        "duration_ms":         float(duration),
        "ground_truth_label":  target_label,
        "is_synthetic":        True,
        "data_source":         data_source,
        "browser_signals":     browser_signals,
        "mouse_events":        mouse_events,
        "keyboard_events":     keyboard_events,
        "scroll_events":       scroll_events,
        "click_events":        click_events,
        "task_actions":        task_actions,
    }

