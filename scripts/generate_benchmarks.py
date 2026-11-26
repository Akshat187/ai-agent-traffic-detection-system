"""
Benchmark Generator & Dataset Assembler for SentinelTrace.

Creates a persistent, versioned empirical benchmark dataset on disk in data/benchmarks/
spanning diverse operational profiles (600 traces: 200 per class), including hard-negative
human subtypes:
- HUMAN (200 traces):
    * organic_mouse (natural Bézier curves, Fitts's deceleration, physiological tremor)
    * keyboard_focused (natural keystroke CV, reading dwell, assistive a11y navigation)
    * fast_power_user (rapid mouse movement and quick clicks with natural micro-corrections)
    * mobile_touch (touchscreen interaction without mousemove trajectories)
    * copy_paste_filler (form-filling with paste events and organic mouse movement)
    * slow_network_lag (long reading/network pauses without post-pause action bursts)
- TRADITIONAL_AUTOMATION (200 traces):
    * deterministic, randomized, evasive, headless_dom
- AGENTIC_AI (200 traces):
    * dom_agent, hybrid_agent, trajectory_agent
"""

import json
import sys
import random
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from packages.generators.seed_data import generate_synthetic_session

DATA_DIR = BASE_DIR / "data" / "benchmarks"


def _apply_hard_negative_profile(session: dict, subtype: str, rng: random.Random) -> dict:
    """Shapes hard-negative human edge cases without leaking into automation."""
    if subtype == "mobile_touch":
        session["mouse_events"] = []
        session["browser_signals"]["touch_support"] = True
        session["browser_signals"]["pointer_type"] = "touch"
        session["browser_signals"]["webdriver"] = False
        session["browser_signals"]["screen_width"] = 390
        session["browser_signals"]["screen_height"] = 844
    elif subtype == "copy_paste_filler":
        for kb in session.get("keyboard_events", [])[:2]:
            kb["is_paste"] = True
    elif subtype == "fast_power_user":
        for ev in session.get("mouse_events", []):
            ev["t"] = max(1, int(ev["t"] * 0.65))
        session["duration_ms"] = max(800.0, session.get("duration_ms", 4000.0) * 0.65)
    elif subtype == "slow_network_lag":
        # Long dwell/network pause without <400ms burstiness
        for i, act in enumerate(session.get("task_actions", [])):
            act["t"] = act.get("t", 1000) + i * rng.randint(1500, 3500)
        session["duration_ms"] = session.get("duration_ms", 5000.0) + 4500.0
    return session


def generate_benchmark_dataset():
    print(f"Creating persistent benchmark dataset in: {DATA_DIR}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    classes = {
        "HUMAN": {
            "dir": DATA_DIR / "human",
            "subtypes": [
                "organic_mouse",
                "keyboard_focused",
                "prompt_typing",
                "fast_power_user",
                "mobile_touch",
                "copy_paste_filler",
                "slow_network_lag",
            ],
            "count": 200,
        },
        "TRADITIONAL_AUTOMATION": {
            "dir": DATA_DIR / "traditional_automation",
            "subtypes": ["deterministic", "randomized", "evasive", "headless_dom"],
            "count": 200,
        },
        "AGENTIC_AI": {
            "dir": DATA_DIR / "agentic_ai",
            "subtypes": ["dom_agent", "hybrid_agent", "trajectory_agent"],
            "count": 200,
        },
    }

    tasks = ["shopping", "travel", "forum"]
    rng = random.Random(1337)
    manifest = {
        "dataset_name": "SentinelTrace Behavioral Ground Truth Benchmark",
        "version": "1.3.0",
        "total_traces": 600,
        "classes": {},
    }

    total_created = 0
    for cls_name, cls_info in classes.items():
        cls_dir = cls_info["dir"]
        cls_dir.mkdir(parents=True, exist_ok=True)
        # Clean old trace files so stale counts don't mix
        for old_file in cls_dir.glob("*.json"):
            old_file.unlink()

        manifest["classes"][cls_name] = {
            "count": cls_info["count"],
            "subtypes": list(set(cls_info["subtypes"])),
            "files": [],
        }

        for i in range(cls_info["count"]):
            subtype = cls_info["subtypes"][i % len(cls_info["subtypes"])]
            base_subtype = (
                "organic_mouse"
                if subtype in ("fast_power_user", "mobile_touch", "copy_paste_filler", "slow_network_lag")
                else subtype
            )
            task = tasks[i % len(tasks)]
            seed = rng.randint(1000, 999999)

            session = generate_synthetic_session(
                label=cls_name,
                task=task,
                index=i + 1,
                seed=seed,
                subtype=base_subtype,
            )
            if cls_name == "HUMAN":
                session = _apply_hard_negative_profile(session, subtype, rng)

            session["is_synthetic"] = False
            session["data_source"] = f"benchmark_{subtype}"
            session["session_id"] = f"bm_{cls_name.lower()}_{subtype}_{task}_{i+1:03d}"

            if subtype == "dom_agent":
                session["active_duration_ms"] = session.get("duration_ms", 6000.0)

            filename = f"{cls_name.lower()}_{subtype}_{i+1:03d}.json"
            filepath = cls_dir / filename
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(session, f, indent=2)

            manifest["classes"][cls_name]["files"].append(filename)
            total_created += 1

    metadata_path = DATA_DIR / "metadata.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Successfully generated {total_created} benchmark sessions across 3 classes.")
    print(f"Metadata written to {metadata_path}")


if __name__ == "__main__":
    generate_benchmark_dataset()
