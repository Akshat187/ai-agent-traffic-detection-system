"""
GDPR/CCPA Data Retention & Telemetry Pruning Job for SentinelTrace.

Strips raw coordinate/keystroke/scroll telemetry (`mouse_events`, `click_events`,
`keyboard_events`, `scroll_events`) from RawTelemetry and TelemetryChunk records
older than the configured TTL (default: 14 days), while retaining anonymized
SessionRecord verdicts, SessionFeatures aggregated metrics, and VerdictHistory.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from packages.database.db import SessionLocal, init_db
from packages.database.models import SessionRecord, RawTelemetry, TelemetryChunk


def prune_expired_telemetry(ttl_days: int = 14, dry_run: bool = False) -> dict:
    """Strips raw coordinate & keystroke telemetry older than ttl_days."""
    init_db()
    cutoff = datetime.utcnow() - timedelta(days=ttl_days)
    db = SessionLocal()
    pruned_raw = 0
    pruned_chunks = 0

    try:
        expired_session_ids = [
            row[0]
            for row in db.query(SessionRecord.session_id)
            .filter(SessionRecord.created_at < cutoff)
            .all()
        ]
        if not expired_session_ids:
            print(f"[Prune] No sessions older than {ttl_days} days (cutoff={cutoff.isoformat()}).")
            return {"expired_sessions": 0, "pruned_raw": 0, "pruned_chunks": 0}

        # Chunk in batches of 500 to stay well below SQLite's 999-variable limit
        BATCH_SIZE = 500
        for start in range(0, len(expired_session_ids), BATCH_SIZE):
            batch_ids = expired_session_ids[start:start + BATCH_SIZE]

            raw_rows = (
                db.query(RawTelemetry)
                .filter(RawTelemetry.session_id.in_(batch_ids))
                .all()
            )
            for raw in raw_rows:
                if raw.mouse_events or raw.click_events or raw.keyboard_events or raw.scroll_events:
                    if not dry_run:
                        raw.mouse_events = []
                        raw.click_events = []
                        raw.keyboard_events = []
                        raw.scroll_events = []
                    pruned_raw += 1

            chunk_rows = (
                db.query(TelemetryChunk)
                .filter(TelemetryChunk.session_id.in_(batch_ids))
                .all()
            )
            for chunk in chunk_rows:
                payload = chunk.payload or {}
                if any(payload.get(k) for k in ("mouse_events", "click_events", "keyboard_events", "scroll_events")):
                    if not dry_run:
                        cleaned = dict(payload)
                        for k in ("mouse_events", "click_events", "keyboard_events", "scroll_events"):
                            if k in cleaned:
                                cleaned[k] = []
                        chunk.payload = cleaned
                    pruned_chunks += 1

        if not dry_run:
            db.commit()

        mode = "DRY-RUN" if dry_run else "APPLIED"
        print(
            f"[Prune:{mode}] TTL={ttl_days}d | expired_sessions={len(expired_session_ids)} | "
            f"pruned_raw={pruned_raw} | pruned_chunks={pruned_chunks}"
        )
        return {
            "expired_sessions": len(expired_session_ids),
            "pruned_raw": pruned_raw,
            "pruned_chunks": pruned_chunks,
        }
    finally:
        db.close()


def main():
    default_ttl = int(os.getenv("TELEMETRY_RETENTION_DAYS", "14"))
    parser = argparse.ArgumentParser(description="Prune raw telemetry older than TTL while keeping anonymized verdicts.")
    parser.add_argument("--ttl-days", type=int, default=default_ttl, help="Retention TTL in days (default: 14)")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be pruned without modifying DB")
    args = parser.parse_args()
    prune_expired_telemetry(ttl_days=args.ttl_days, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
