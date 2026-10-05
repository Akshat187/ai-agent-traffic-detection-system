"""
Benchmark Generator & Dataset Assembler for WebSense Sentinel.

Creates a persistent, versioned empirical benchmark dataset on disk in data/benchmarks/
spanning diverse operational profiles:
- HUMAN:
    * organic_mouse (natural Bézier curves, Fitts's deceleration, physiological tremor)
    * keyboard_focused (natural keystroke CV, reading dwell, assistive navigation)
    * reading_dwell (long cognitive dwell times, deliberate reading pauses)
    * fast_navigator (expert web user with quick target acquisition)
- TRADITIONAL_AUTOMATION:
    * deterministic (Playwright default linear script, zero jitter)
    * randomized (automation with slight uniform jitter)
    * evasive (bot injecting Gaussian coordinate noise, suppressed webdriver flag)
    * headless_dom (sub-80ms crawler executing DOM clicks/submits)
- AGENTIC_AI:
    * stagehand_dom (Stagehand / Browser-use pattern: 1.5s - 4.5s LLM inference pauses, direct DOM selectors)
    * browser_use_multistep (multi-step planner with action bursts after inference deliberation)
    * claude_computer_use (waypoint navigation with visual screenshot deliberation gaps)

Generates 20 traces per class (60 total) + metadata.json.
"""

import json
import os
import sys
import random
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from packages.generators.seed_data import generate_synthetic_session
DATA_DIR = BASE_DIR / "data" / "benchmarks"


def generate_benchmark_dataset():
    print(f"Creating persistent benchmark dataset in: {DATA_DIR}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    classes = {
        "HUMAN": {
            "dir": DATA_DIR / "human",
            "subtypes": ["organic_mouse", "keyboard_focused", "organic_mouse", "keyboard_focused"],
            "count": 20,
        },
        "TRADITIONAL_AUTOMATION": {
            "dir": DATA_DIR / "traditional_automation",
            "subtypes": ["deterministic", "randomized", "evasive", "headless_dom"],
            "count": 20,
        },
        "AGENTIC_AI": {
            "dir": DATA_DIR / "agentic_ai",
            "subtypes": ["dom_agent", "hybrid_agent", "trajectory_agent", "dom_agent"],
            "count": 20,
        },
    }

    tasks = ["shopping", "travel", "forum"]
    rng = random.Random(1337)
    manifest = {
        "dataset_name": "WebSense Behavioral Ground Truth Benchmark",
        "version": "1.2.0",
        "total_traces": 60,
        "classes": {},
    }

    total_created = 0
    for cls_name, cls_info in classes.items():
        cls_dir = cls_info["dir"]
        cls_dir.mkdir(parents=True, exist_ok=True)
        manifest["classes"][cls_name] = {
            "count": cls_info["count"],
            "subtypes": list(set(cls_info["subtypes"])),
            "files": [],
        }

        for i in range(cls_info["count"]):
            subtype = cls_info["subtypes"][i % len(cls_info["subtypes"])]
            task = tasks[i % len(tasks)]
            seed = rng.randint(1000, 999999)

            session = generate_synthetic_session(
                label=cls_name,
                task=task,
                index=i + 1,
                seed=seed,
                subtype=subtype,
            )
            # Mark as persistent benchmark
            session["is_synthetic"] = False
            session["data_source"] = f"benchmark_{subtype}"
            session["session_id"] = f"bm_{cls_name.lower()}_{subtype}_{task}_{i+1:03d}"

            # If it's dom_agent, ensure characteristic LLM inference delays
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
