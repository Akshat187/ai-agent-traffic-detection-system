"""
Seed API Endpoint — Generates demonstrative ground-truth dataset.

Key guarantees:
  - Tasks are RANDOMLY shuffled within each class (not deterministic round-robin).
  - Each class gets approximately equal coverage of all 3 tasks.
  - All seeded sessions are labeled data_source='synthetic_demo' for dashboard demarcation.
  - Uses the centralized repository layer — no duplicate DB code.
"""

import random
from typing import Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from packages.database.db import get_db
from packages.database.repository import create_session
from packages.generators.seed_data import generate_synthetic_session
from packages.core.features import extract_all_features
from apps.api.dependencies import get_detection_engine, DecisionEngine
from apps.api.config import settings

router = APIRouter(prefix="/api/v1/seed", tags=["Seed"])


@router.post("/demo")
def seed_demo_data(
    count_per_class: int = 30,
    seed: int = 42,
    db: Session = Depends(get_db),
    engine: DecisionEngine = Depends(get_detection_engine),
) -> Dict[str, Any]:
    """
    Populates the database with a balanced synthetic dataset across
    HUMAN, TRADITIONAL_AUTOMATION, and AGENTIC_AI classes.

    Task assignment is randomly shuffled (not round-robin) so that the
    model cannot learn task→class correlations from the training data.
    Each class receives approximately equal representation of all 3 tasks.

    All sessions are labeled as data_source='synthetic_demo' so the
    dashboard can clearly flag them as DEMO DATA.
    """
    rng = random.Random(seed)
    classes = ["HUMAN", "TRADITIONAL_AUTOMATION", "AGENTIC_AI"]
    valid_tasks = settings.VALID_TASKS  # ["shopping", "travel", "community"]
    created_count = 0
    skipped_count = 0

    for cls in classes:
        # Build a randomized task list: each task appears count_per_class/3 times (approx)
        # This guarantees class-task independence in the aggregate dataset.
        tasks_for_class = (valid_tasks * (count_per_class // len(valid_tasks) + 1))[:count_per_class]
        rng.shuffle(tasks_for_class)

        for i, task in enumerate(tasks_for_class, start=1):
            session_dict = generate_synthetic_session(
                label=cls,
                task=task,
                index=i,
                seed=rng.randint(0, 10_000),
            )
            session_id = session_dict["session_id"]

            # Skip if already in DB (idempotent seeding)
            from packages.database.models import SessionRecord
            if db.query(SessionRecord).filter_by(session_id=session_id).first():
                skipped_count += 1
                continue

            features = extract_all_features(session_dict)
            verdict  = engine.evaluate_session(
                session_id=session_id,
                task=task,
                session_data=session_dict,
                features=features,
            )

            # Use repository layer — single authoritative write path
            create_session(
                db=db,
                session_dict=session_dict,
                features=features,
                verdict=verdict,
                data_source="synthetic_demo",
                ground_truth_label=cls,
                is_synthetic=True,
            )
            created_count += 1

    db.commit()

    return {
        "status":        "success",
        "created":       created_count,
        "skipped":       skipped_count,
        "total_in_db":   db.query(__import__('packages.database.models', fromlist=['SessionRecord']).SessionRecord).count(),
        "data_source":   "synthetic_demo",
        "note":          "All sessions labeled as synthetic demo data. Dashboard will display DEMO DATA badge.",
        "task_balance":  "Randomized — tasks shuffled within each class to prevent task→label correlation.",
    }
