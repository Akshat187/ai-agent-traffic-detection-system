"""
Standalone Demo Data Seeder for WebSense.
Run: python demo_seed.py
"""

from packages.database.db import init_db, SessionLocal
from packages.detection.engine import DecisionEngine
from apps.api.routes.seed import seed_demo_data

if __name__ == "__main__":
    print("[WebSense] Initializing database and seeding realistic demo dataset...")
    init_db()
    db = SessionLocal()
    engine = DecisionEngine()
    try:
        res = seed_demo_data(count_per_class=12, db=db, engine=engine)
        count = res.get('created', res.get('count', 0))
        print(f"[WebSense] Successfully populated {count} labeled sessions across HUMAN, TRADITIONAL_AUTOMATION, and AGENTIC_AI classes!")
    finally:
        db.close()

