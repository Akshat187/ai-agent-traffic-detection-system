"""
Live Bot & AI Agent Traffic Demonstrator for WebSense Sentinel.

Allows students, researchers, and engineers to demonstrate live Bot and
AI Browser Agent detection to their project guides, mentors, or reviewers.

Sends real-time behavioral streams to the local WebSense engine and prints
the 5-Layer verdict in the terminal, while simultaneously updating the
live Security Dashboard at http://localhost:8000/dashboard.

Usage:
    python scripts/simulate_live_bot.py --type ai_agent
    python scripts/simulate_live_bot.py --type bot
    python scripts/simulate_live_bot.py --type evasive
    python scripts/simulate_live_bot.py --type human
"""

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from packages.generators.seed_data import (
    generate_synthetic_session,
    generate_bot_mouse_path,
    generate_human_mouse_path,
)

SERVER_URL = "http://127.0.0.1:8000/api/v1/sessions"


def create_payload(actor_type: str, site_id: str = "site_meridian_prod"):
    rng = random.Random()
    session_id = f"demo_{actor_type}_{uuid.uuid4().hex[:8]}"
    start_unix = int(time.time() * 1000)

    if actor_type == "bot":
        # Classic Playwright / Selenium headless bot
        mouse_events = generate_bot_mouse_path(150, 150, 780, 520, 350, jitter_sigma=0.0, rng=rng)
        kb_events = [
            {"t": 100 + i * 40, "interval": 40, "hold": 20, "is_paste": False}
            for i in range(15)
        ]
        return {
            "session_id": session_id,
            "page_visit_id": session_id,
            "journey_id": f"jny_bot_{uuid.uuid4().hex[:6]}",
            "site_id": site_id,
            "visitor_id": f"vis_bot_{uuid.uuid4().hex[:6]}",
            "task": "shopping",
            "seq": 1,
            "final": True,
            "client_context": {
                "tab_id": "tab_playwright_worker_0",
                "page_path": "/visitor/shop",
                "page_title": "Shop — Meridian",
                "page_url": "http://localhost:8000/visitor/shop",
                "visibility_state": "visible",
                "transmission_seq": 1,
                "sdk_version": "sentinel-2.1"
            },
            "start_time": start_unix - 3500,
            "end_time": start_unix,
            "duration_ms": 3500,
            "active_duration_ms": 3500,
            "data_source": "realtime_sdk",
            "browser_signals": {
                "webdriver": True,
                "screen_width": 1920,
                "screen_height": 1080,
                "viewport_width": 1280,
                "viewport_height": 800,
                "user_agent": "Mozilla/5.0 (HeadlessChrome; Playwright) AppleWebKit/537.36"
            },
            "mouse_events": mouse_events,
            "keyboard_events": kb_events,
            "scroll_events": [],
            "click_events": [{"x": 780, "y": 520, "t": 360, "target_category": "button"}],
            "task_actions": [{"action": "button_trigger", "t": 370, "details": {"label": "Add to Cart"}}]
        }

    elif actor_type == "evasive":
        # Bot hiding webdriver and adding Gaussian noise, but failing Fitts's law deceleration
        mouse_events = generate_bot_mouse_path(120, 180, 820, 560, 1800, jitter_sigma=16.0, rng=rng)
        kb_events = [
            {"t": 120 + i * 45, "interval": 45, "hold": 22, "is_paste": False}
            for i in range(12)
        ]
        return {
            "session_id": session_id,
            "page_visit_id": session_id,
            "journey_id": f"jny_evasive_{uuid.uuid4().hex[:6]}",
            "site_id": site_id,
            "visitor_id": f"vis_evasive_{uuid.uuid4().hex[:6]}",
            "task": "shopping",
            "seq": 1,
            "final": True,
            "client_context": {
                "tab_id": "tab_stealth_pup_1",
                "page_path": "/visitor/shop",
                "page_title": "Shop — Meridian",
                "page_url": "http://localhost:8000/visitor/shop",
                "visibility_state": "visible",
                "transmission_seq": 1,
                "sdk_version": "sentinel-2.1"
            },
            "start_time": start_unix - 4200,
            "end_time": start_unix,
            "duration_ms": 4200,
            "active_duration_ms": 4200,
            "data_source": "realtime_sdk",
            "browser_signals": {
                "webdriver": False,  # Concealed
                "screen_width": 1920,
                "screen_height": 1080,
                "viewport_width": 1280,
                "viewport_height": 800,
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"
            },
            "mouse_events": mouse_events,
            "keyboard_events": kb_events,
            "scroll_events": [],
            "click_events": [{"x": 820, "y": 560, "t": 1820, "target_category": "button"}],
            "task_actions": [{"action": "button_trigger", "t": 1830, "details": {"label": "Add to Cart"}}]
        }

    elif actor_type == "ai_agent":
        # Autonomous AI Browser Agent (Stagehand / Browser-use / Claude Computer Use)
        # Multi-second LLM inference deliberation pause (2.6s) followed by rapid action burst
        return {
            "session_id": session_id,
            "page_visit_id": session_id,
            "journey_id": f"jny_agent_{uuid.uuid4().hex[:6]}",
            "site_id": site_id,
            "visitor_id": f"vis_stagehand_{uuid.uuid4().hex[:6]}",
            "task": "shopping",
            "seq": 1,
            "final": True,
            "client_context": {
                "tab_id": "tab_agent_runner",
                "page_path": "/visitor/shop",
                "page_title": "Shop — Meridian",
                "page_url": "http://localhost:8000/visitor/shop",
                "visibility_state": "visible",
                "transmission_seq": 1,
                "sdk_version": "sentinel-2.1"
            },
            "start_time": start_unix - 8500,
            "end_time": start_unix,
            "duration_ms": 8500,
            "active_duration_ms": 8500,
            "data_source": "realtime_sdk",
            "browser_signals": {
                "webdriver": False,
                "screen_width": 1440,
                "screen_height": 900,
                "viewport_width": 1440,
                "viewport_height": 720,
                "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0"
            },
            # Direct DOM clicks with multi-second LLM inference deliberation gaps
            "mouse_events": [],
            "keyboard_events": [
                {"t": 2800, "interval": 42, "hold": 30, "is_paste": False},
                {"t": 2845, "interval": 45, "hold": 28, "is_paste": False},
                {"t": 2890, "interval": 45, "hold": 32, "is_paste": False}
            ],
            "scroll_events": [
                {"t": 3100, "scroll_y": 450, "delta_y": 450}
            ],
            "click_events": [
                {"x": 420, "y": 380, "t": 2750, "target_category": "input"},
                {"x": 750, "y": 510, "t": 5900, "target_category": "button"}
            ],
            "task_actions": [
                {"action": "product_search", "t": 2750, "details": {"query_length": 8}},
                {"action": "button_trigger", "t": 5900, "details": {"label": "Add to Cart"}}
            ]
        }

    else:  # human
        h_sess = generate_synthetic_session("HUMAN", task="shopping", subtype="organic_mouse", seed=rng.randint(1000, 999999))
        h_sess["session_id"] = session_id
        h_sess["page_visit_id"] = session_id
        h_sess["site_id"] = site_id
        h_sess["data_source"] = "realtime_sdk"
        h_sess["seq"] = 1
        h_sess["final"] = True
        return h_sess


def run_demo(actor_type: str, site_id: str = "site_meridian_prod"):
    print("\n" + "=" * 65)
    print(f"WEBSENSE SENTINEL — LIVE TRAFFIC INJECTION: [{actor_type.upper()}]")
    print("=" * 65)
    print(f"Target Endpoint : {SERVER_URL}")
    print(f"Honey Site ID   : {site_id}")

    payload = create_payload(actor_type, site_id)
    session_id = payload["session_id"]
    print(f"Session ID      : {session_id}")
    print(f"Transmitting realistic {actor_type} behavioral telemetry...")

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        SERVER_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Origin": "http://localhost:8000",
            "Referer": "http://localhost:8000/visitor/shop"
        }
    )

    try:
        t0 = time.perf_counter()
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode())
        dt = (time.perf_counter() - t0) * 1000.0

        print(f"\n[Response Received in {dt:.1f} ms]")
        print("-" * 65)
        print(f"FINAL VERDICT       : {res_data.get('predicted_label')}")
        print(f"RISK SCORE          : {res_data.get('risk_score', 0)} / 100")
        print(f"CONFIDENCE          : {res_data.get('confidence', 0):.1f}%")
        print(f"LAYER 1 (Rules)     : Score {res_data.get('l1_rule_score')}")
        print(f"LAYER 2 (ML Model)  : {res_data.get('l2_ml_pred')}")
        print(f"LAYER 3 (Anomaly)   : {'ANOMALOUS OUTLIER' if res_data.get('l3_is_anomaly') else 'Within baseline'}")
        print(f"LAYER 4 (Replay)    : {'REPLAY DETECTED' if res_data.get('l4_is_replay') else 'Original motion'}")
        print(f"LAYER 5 (Context)   : Status {res_data.get('l5_status')}")

        print("\nCONTRIBUTING EVIDENCE SIGNALS:")
        for sig in res_data.get("contributing_signals", []):
            print(f"  * {sig}")

        print("-" * 65)
        print(f"Check the Dashboard now: http://localhost:8000/dashboard")
        print(f"Session {session_id} is now logged at the top of the table!")
        print("=" * 65 + "\n")

    except urllib.error.URLError as e:
        print(f"\n[ERROR] Could not connect to WebSense server at {SERVER_URL}.")
        print("Ensure the server is running with: python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000")
        print(f"Details: {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inject live bot or AI agent traffic for live demonstrations.")
    parser.add_argument(
        "--type",
        choices=["ai_agent", "bot", "evasive", "human"],
        default="ai_agent",
        help="Type of actor to simulate (default: ai_agent)"
    )
    parser.add_argument(
        "--site",
        default="site_meridian_prod",
        help="Site ID (default: site_meridian_prod for the Honey Site, or site_chrome_extension)"
    )
    args = parser.parse_args()
    run_demo(args.type, args.site)
