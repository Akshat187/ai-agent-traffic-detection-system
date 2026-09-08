"""
Dependency Injection Providers for FastAPI Routes.
"""

from packages.database.db import get_db
from packages.detection.engine import DecisionEngine

# Global singleton DecisionEngine instance
detection_engine = DecisionEngine()


def get_detection_engine() -> DecisionEngine:
    """Provides the singleton instance of the 5-layer detection engine."""
    return detection_engine
