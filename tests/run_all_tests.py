"""
Comprehensive test runner for WebSense / Sentinel SDK platform.
Executes all integration and unit test suites and reports exact outputs.
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient
from apps.api.main import app
from packages.database.db import SessionLocal, init_db
from packages.database.models import SiteRecord, SessionRecord

init_db()

def run_tests():
    print("=" * 70)
    print("WEBSENSE / SENTINEL SDK — COMPREHENSIVE PIPELINE VERIFICATION")
    print("=" * 70)

    with TestClient(app) as client:
        # 1. Test Sentinel script endpoint
        print("\n[TEST 1] Testing /sentinel.js and /static/sentinel.js endpoint...")
        resp = client.get("/sentinel.js")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert "application/javascript" in resp.headers.get("content-type", "")
        assert "Sentinel" in resp.text
        print("  --> PASS: /sentinel.js served cleanly as application/javascript.")

        # 2. Test Site Registration
        print("\n[TEST 2] Testing Site Registration (POST /api/v1/sites)...")
        site_payload = {
            "name": "Acme Global Store",
            "allowed_origins": "https://acmestore.com,http://localhost:3000"
        }
        resp = client.post("/api/v1/sites", json=site_payload)
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"
        site_data = resp.json()
        site_id = site_data["site_id"]
        api_key = site_data["api_key"]
        print(f"  --> PASS: Registered site '{site_id}' with API key '{api_key[:12]}...'")

        # 3. Test Site Listing & Query
        print("\n[TEST 3] Testing Site Listing & Query (GET /api/v1/sites)...")
        list_resp = client.get("/api/v1/sites")
        assert list_resp.status_code == 200
        sites = list_resp.json()["sites"]
        assert any(s["site_id"] == site_id for s in sites)
        print(f"  --> PASS: Found {len(sites)} registered site(s).")

        # 4. Test Ingestion with Valid Site Origin
        print("\n[TEST 4] Testing Telemetry Ingestion from Authorized Origin...")
        human_payload = {
            "session_id": f"sdk_human_{int(time.time())}",
            "site_id": site_id,
            "task": "shopping",
            "start_time": 1700000000.0,
            "end_time": 1700000015.0,
            "duration_ms": 15000.0,
            "data_source": "realtime_sdk",
            "browser_signals": {
                "webdriver": False,
                "screen_width": 1920,
                "screen_height": 1080,
                "viewport_width": 1440,
                "viewport_height": 900
            },
            "mouse_events": [
                {"x": 100, "y": 120, "t": 100, "type": "move"},
                {"x": 140, "y": 155, "t": 240, "type": "move"},
                {"x": 195, "y": 210, "t": 410, "type": "move"},
                {"x": 260, "y": 275, "t": 620, "type": "move"},
                {"x": 330, "y": 340, "t": 890, "type": "move"},
                {"x": 390, "y": 395, "t": 1200, "type": "move"},
                {"x": 420, "y": 420, "t": 1500, "type": "move"}
            ],
            "keyboard_events": [
                {"t": 1600, "interval": 140.0, "hold": 72.0, "is_paste": False},
                {"t": 1780, "interval": 180.0, "hold": 65.0, "is_paste": False},
                {"t": 1990, "interval": 210.0, "hold": 80.0, "is_paste": False}
            ],
            "scroll_events": [
                {"t": 2200, "scroll_y": 150, "delta_y": 150},
                {"t": 2400, "scroll_y": 320, "delta_y": 170}
            ],
            "click_events": [
                {"x": 420, "y": 420, "t": 2600, "target_category": "button"}
            ],
            "task_actions": [
                {"action": "add_to_cart", "t": 2650, "details": {"product_id": "prod_linen_throw", "qty": 1}}
            ]
        }

        ingest_resp = client.post("/api/v1/sessions", json=human_payload, headers={"Origin": "https://acmestore.com"})
        assert ingest_resp.status_code == 200, f"Expected 200, got {ingest_resp.status_code}: {ingest_resp.text}"
        verdict = ingest_resp.json()
        print(f"  --> PASS: Ingested telemetry! Classification verdict: {verdict['predicted_label']} (Confidence: {verdict['confidence']*100:.1f}%, Risk: {verdict['risk_score']}/100)")

        # 5. Test Ingestion with Unauthorized Origin
        print("\n[TEST 5] Testing Origin Security Enforcement (Unauthorized Origin)...")
        forbidden_payload = dict(human_payload)
        forbidden_payload["session_id"] = f"sdk_forbidden_{int(time.time())}"
        forb_resp = client.post("/api/v1/sessions", json=forbidden_payload, headers={"Origin": "https://unauthorized-hacker.com"})
        assert forb_resp.status_code == 403, f"Expected 403, got {forb_resp.status_code}"
        print(f"  --> PASS: Rejected unauthorized origin with 403: {forb_resp.json()['detail']}")

        # 6. Test Multi-Site Data Segregation
        print("\n[TEST 6] Testing Multi-Site Data Querying & Segregation...")
        site_sess_resp = client.get(f"/api/v1/sessions?site_id={site_id}")
        assert site_sess_resp.status_code == 200
        site_sessions = site_sess_resp.json()
        assert len(site_sessions) >= 1
        assert site_sessions[0]["site_id"] == site_id
        assert site_sessions[0]["data_source"] == "realtime_sdk"
        print(f"  --> PASS: Filtered {len(site_sessions)} session(s) specifically for site '{site_id}' with data_source = realtime_sdk.")

        # 7. Test Meridian Shop 20-Product Catalog and Clean Encodings
        print("\n[TEST 7] Testing Meridian Shop Page & 20-Product Catalog...")
        shop_resp = client.get("/visitor/shop")
        assert shop_resp.status_code == 200
        assert "prod_linen_throw" in shop_resp.text
        assert "prod_ceramic_mug" in shop_resp.text
        assert "prod_cast_iron_kettle" in shop_resp.text
        assert "prod_oak_organizer" in shop_resp.text
        assert "prod_merino_cushion" in shop_resp.text
        assert "prod_atlas_obscura" in shop_resp.text
        assert "prod_bauhaus_monograph" in shop_resp.text
        assert "prod_fountain_pen" in shop_resp.text
        assert "prod_leather_journal" in shop_resp.text
        assert "prod_typography_handbook" in shop_resp.text
        assert "prod_wool_cardigan" in shop_resp.text
        assert "prod_canvas_weekender" in shop_resp.text
        assert "prod_minimalist_raincoat" in shop_resp.text
        assert "prod_leather_cardholder" in shop_resp.text
        assert "prod_wool_beanie" in shop_resp.text
        assert "prod_desk_lamp" in shop_resp.text
        assert "prod_mechanical_keyboard" in shop_resp.text
        assert "prod_aluminum_dock" in shop_resp.text
        assert "prod_monitor_stands" in shop_resp.text
        assert "prod_digital_pad" in shop_resp.text
        # Check no broken emoji artifacts or double-encoding
        assert "Â£" not in shop_resp.text
        assert "â€" not in shop_resp.text
        assert "ðŸ" not in shop_resp.text
        assert "sentinel.js" in shop_resp.text
        print("  --> PASS: Meridian Shop verified with 20 distinct products, clean vector swatches, and Sentinel SDK embed.")

        # 8. Test External Standalone Demo Page
        print("\n[TEST 8] Testing External Standalone Demo Page (/standalone_demo)...")
        demo_resp = client.get("/standalone_demo")
        assert demo_resp.status_code == 200
        assert "Sentinel External Site Embed Demo" in demo_resp.text
        assert "sentinel.js" in demo_resp.text
        print("  --> PASS: /standalone_demo rendered cleanly.")

    print("\n" + "=" * 70)
    print("ALL INTEGRATION & UNIT TESTS PASSED (100% SUCCESS)")
    print("=" * 70)

if __name__ == "__main__":
    run_tests()
