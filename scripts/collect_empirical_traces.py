"""
Empirical Trace Collector & Evaluation Harness.

Generates and evaluates realistic, non-trivial interaction traces for:
1. TRADITIONAL_AUTOMATION:
   - Headless DOM scrapers (sub-80ms action intervals, zero cursor movements)
   - Fast linear Playwright scripts
   - Evasive bots with artificial jitter and suppressed webdriver flag
2. AGENTIC_AI:
   - Direct DOM LLM browser agents (Stagehand / Browser-use pattern: 1.5 - 4.5s inference wait, zero mouse movements)
   - Coordinate-based agents (Claude Computer Use pattern: waypoints + deliberation pauses)
   - Hybrid agents (reading scroll + contextual actions)
3. HUMAN:
   - Real organic Bézier kinematics, variable typing cadence, natural dwell times

Usage:
  python scripts/collect_empirical_traces.py [--server http://localhost:8000] [--count 10]
"""

import sys
import os
import time
import argparse
import random
from pathlib import Path
from typing import Dict, Any, List

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.chdir(str(BASE_DIR))

from packages.generators.seed_data import generate_synthetic_session
from packages.core.features import extract_all_features
from packages.detection.engine import DecisionEngine


def run_evaluation_benchmark(count_per_class: int = 15, transmit_endpoint: str = None):
    print("=" * 70)
    print("WebSense Sentinel — Empirical Trace Evaluation Harness")
    print(f"Generating {count_per_class} traces per class across diverse operational profiles...")
    print("=" * 70)

    engine = DecisionEngine()
    results = {
        "HUMAN": {"HUMAN": 0, "TRADITIONAL_AUTOMATION": 0, "AGENTIC_AI": 0, "UNCERTAIN": 0},
        "TRADITIONAL_AUTOMATION": {"HUMAN": 0, "TRADITIONAL_AUTOMATION": 0, "AGENTIC_AI": 0, "UNCERTAIN": 0},
        "AGENTIC_AI": {"HUMAN": 0, "TRADITIONAL_AUTOMATION": 0, "AGENTIC_AI": 0, "UNCERTAIN": 0},
    }

    subtypes = {
        "HUMAN": ["organic_mouse", "keyboard_focused"],
        "TRADITIONAL_AUTOMATION": ["headless_dom", "deterministic", "randomized", "evasive"],
        "AGENTIC_AI": ["dom_agent", "hybrid_agent", "trajectory_agent"],
    }

    tasks = ["shopping", "travel", "forum"]
    rng = random.Random(42)

    client = None
    if transmit_endpoint:
        import httpx
        client = httpx.Client(timeout=10.0)
        print(f"Live HTTP transmission active -> {transmit_endpoint}/api/v1/sessions\n")

    for true_label in ["HUMAN", "TRADITIONAL_AUTOMATION", "AGENTIC_AI"]:
        print(f"\nEvaluating Ground Truth: {true_label}")
        print("-" * 50)
        for i in range(count_per_class):
            task = rng.choice(tasks)
            st = rng.choice(subtypes[true_label]) if true_label in subtypes else None
            session = generate_synthetic_session(
                label=true_label,
                task=task,
                index=i + 1,
                seed=rng.randint(0, 100000),
                subtype=st,
            )

            # Optional live API transmission
            if client:
                try:
                    resp = client.post(f"{transmit_endpoint}/api/v1/sessions", json=session)
                    api_verdict = resp.json().get("final_verdict") if resp.status_code == 200 else None
                except Exception as e:
                    api_verdict = None

            feats = extract_all_features(session)
            verdict = engine.evaluate_session(
                session_id=session["session_id"],
                task=task,
                session_data=session,
                features=feats,
            )
            pred = verdict["final_verdict"]
            results[true_label][pred] = results[true_label].get(pred, 0) + 1

            status = "PASS" if pred == true_label else ("WARN" if pred == "UNCERTAIN" else "FAIL")
            print(
                f"[{status}] Profile: {st:16s} | Path: {len(session['mouse_events']):3d} pts | "
                f"Actions: {len(session['task_actions']):1d} | Pause: {feats.get('planning_pause_ratio', 0):.2f} | "
                f"Predicted: {pred:22s} (conf: {verdict['confidence']:.0f}%, risk: {verdict['risk_score']:.0f})"
            )

    print("\n" + "=" * 70)
    print("Empirical Confusion Matrix:")
    print("=" * 70)
    header = f"{'Ground Truth':24s} | {'Human':8s} | {'Traditional Bot':16s} | {'Agentic AI':12s} | {'Uncertain':10s}"
    print(header)
    print("-" * len(header))
    for true_label in ["HUMAN", "TRADITIONAL_AUTOMATION", "AGENTIC_AI"]:
        row = results[true_label]
        h = row.get("HUMAN", 0)
        b = row.get("TRADITIONAL_AUTOMATION", 0)
        a = row.get("AGENTIC_AI", 0)
        u = row.get("UNCERTAIN", 0)
        print(f"{true_label:24s} | {h:8d} | {b:16d} | {a:12d} | {u:10d}")

    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect and evaluate empirical traces")
    parser.add_argument("--server", type=str, default=None, help="Base URL of live API (e.g. http://localhost:8000)")
    parser.add_argument("--count", type=int, default=15, help="Number of traces to generate per class")
    args = parser.parse_args()

    run_evaluation_benchmark(count_per_class=args.count, transmit_endpoint=args.server)
