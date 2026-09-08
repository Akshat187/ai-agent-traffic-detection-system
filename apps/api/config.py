"""
WebSense Platform Configuration.
Behavioral Intelligence for the Modern Web — v1.2.0
"""

import os
from pydantic import BaseModel


class Settings(BaseModel):
    APP_NAME: str = "WebSense — Behavioral Intelligence for the Modern Web"
    APP_VERSION: str = "1.2.0"
    DEBUG: bool = os.getenv("DEBUG", "False").lower() in ("true", "1")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./sentineltrace.db")
    CORS_ORIGINS: list = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",") if origin.strip()]

    # Model & Schema Versioning
    MODEL_VERSION: str = "v1.2.0-actor-inference"
    FEATURE_SCHEMA_VERSION: str = "v1.2"

    # Classification thresholds
    CONFIDENCE_THRESHOLD: float = 60.0   # Below this → UNCERTAIN
    STRAIGHTNESS_AUTOMATION_THRESHOLD: float = 0.95
    KEY_CV_UNIFORMITY_THRESHOLD: float = 0.05
    REPLAY_SIMILARITY_THRESHOLD: float = 0.94
    ANOMALY_OUTLIER_THRESHOLD: float = 0.0

    # Agentic behavior thresholds
    PLANNING_PAUSE_THRESHOLD_MS: float = 800.0   # Pauses > 800ms = deliberate planning pause
    MIN_PLANNING_PAUSES_FOR_AGENTIC: int = 2      # Min planning pauses to register agency signal
    NAV_SEGMENT_AGENTIC_THRESHOLD: int = 3        # Min distinct cursor segments for agentic signature
    ADAPTATION_SCORE_THRESHOLD: float = 0.4       # Adaptation ratio for agentic classification

    # Signal hierarchy weights (behavioral > environmental)
    BEHAVIORAL_SIGNAL_WEIGHT: float = 0.75
    ENVIRONMENTAL_SIGNAL_WEIGHT: float = 0.25

    # Valid domain values (used for input validation)
    VALID_TASKS: list = ["shopping", "travel", "forum"]
    # Actor classes: HUMAN, TRADITIONAL_AUTOMATION, AGENTIC_AI, UNCERTAIN
    VALID_LABELS: list = ["HUMAN", "TRADITIONAL_AUTOMATION", "AGENTIC_AI", "UNCERTAIN"]
    VALID_DATA_SOURCES: list = [
        "real",
        "synthetic_demo",
        "synthetic_test",
        "synthetic_simulated_agent",
        "synthetic_automation",   # renamed from synthetic_bot
        "synthetic_bot",          # legacy alias — accepted but mapped on write
    ]

    # Minimum labeled sessions per class required before running real experiments
    MIN_EXPERIMENT_SAMPLES_PER_CLASS: int = 6

    # External Agent configuration (optional — app works without these)
    AGENT_PROVIDER: str = os.getenv("AGENT_PROVIDER", "")
    AGENT_MODEL: str = os.getenv("AGENT_MODEL", "")
    AGENT_API_KEY: str = os.getenv("AGENT_API_KEY", "")


settings = Settings()
