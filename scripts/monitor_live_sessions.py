"""
Live Session Telemetry Monitor for WebSense.
Prints incoming real-time sessions received by the API backend.
"""

import time
import sys
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from packages.database.db import SessionLocal
from packages.database.models import SessionRecord

def monitor(poll_interval: float = 1.0, max_duration: int = 3600):
    print("=" * 70)
    print("WebSense Sentinel — Real-Time Live Telemetry Stream Monitor")
    print("Listening for incoming sessions from Chrome Extension & Websites...")
    print("=" * 70)

    db = SessionLocal()
    start_time = datetime.utcnow()
    seen_ids = set()

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Monitoring active. Waiting for incoming telemetry...")
    print("-" * 70)

    elapsed = 0
    try:
        while elapsed < max_duration:
            time.sleep(poll_interval)
            elapsed += int(poll_interval)

            new_sessions = (
                db.query(SessionRecord)
                .filter(SessionRecord.created_at >= start_time)
                .order_by(SessionRecord.created_at.asc())
                .all()
            )

            for s in new_sessions:
                if s.session_id in seen_ids:
                    continue
                seen_ids.add(s.session_id)
                n_mouse = len(s.telemetry.mouse_events) if s.telemetry and s.telemetry.mouse_events else 0
                n_keys = len(s.telemetry.keyboard_events) if s.telemetry and s.telemetry.keyboard_events else 0
                n_clicks = len(s.telemetry.click_events) if s.telemetry and s.telemetry.click_events else 0

                label = s.predicted_label or "UNCERTAIN"
                print(f"\n[NEW SESSION INGESTED] -> {datetime.now().strftime('%H:%M:%S')}")
                print(f"  Session ID:      {s.session_id}")
                print(f"  Data Source:     {s.data_source} (Site: {s.site_id})")
                print(f"  Page URL:        {s.page_url or s.page_path or 'N/A'}")
                print(f"  Events Captured: {n_mouse} mouse, {n_keys} keys, {n_clicks} clicks")
                print(f"  Active Duration: {(s.active_ms or 0)/1000:.1f}s (Total: {(s.duration_ms or 0)/1000:.1f}s)")
                print(f"  CLASSIFICATION:  >>> {label} <<<")
                print(f"  Confidence:      {s.confidence:.1f}%")
                print(f"  Risk Score:      {s.risk_score:.1f} / 100")
                if s.verdict and s.verdict.human_explanation:
                    print(f"  Reasoning:       {s.verdict.human_explanation[:140]}...")
                print("-" * 70)
                sys.stdout.flush()
    finally:
        db.close()

if __name__ == "__main__":
    monitor()
