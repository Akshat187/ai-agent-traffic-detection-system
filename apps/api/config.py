"""
WebSense Platform Configuration.
Behavioral Intelligence for the Modern Web.
"""

import os
from pydantic import BaseModel

from packages.version import APP_VERSION, MODEL_VERSION, FEATURE_SCHEMA_VERSION


class Settings(BaseModel):
    APP_NAME: str = "WebSense — Behavioral Intelligence for the Modern Web"
    APP_VERSION: str = APP_VERSION
    DEBUG: bool = os.getenv("DEBUG", "False").lower() in ("true", "1")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./sentineltrace.db")
    CORS_ORIGINS: list = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",") if origin.strip()]

    # Model & Schema Versioning (single source: packages/version.py)
    MODEL_VERSION: str = MODEL_VERSION
    FEATURE_SCHEMA_VERSION: str = FEATURE_SCHEMA_VERSION

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

    # Valid domain values (used for input validation).
    # VALID_TASKS: everything the ingest API accepts (unknown values → 422).
    # WORKFLOW_TASKS: tasks that have Layer-5 workflow rules. For any other task
    # Layer 5 is reported as "not_applicable", never as "valid".
    VALID_TASKS: list = ["general", "shopping", "travel", "forum", "custom"]
    WORKFLOW_TASKS: list = ["shopping", "travel", "forum"]
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

    # Default sites provisioned at startup. Sites are never auto-created on ingest.
    DEFAULT_SITE_ID: str = "site_meridian_prod"
    EXTENSION_SITE_ID: str = "site_chrome_extension"

    # Ingest limits
    # Per-session throttle: a page visit normally sends one chunk every 5 s.
    INGEST_MAX_CHUNKS_PER_SESSION_PER_MIN: int = int(os.getenv("INGEST_MAX_CHUNKS_PER_SESSION_PER_MIN", "60"))
    # Coarse per-IP abuse guard (many tabs behind one NAT must still fit).
    INGEST_MAX_REQUESTS_PER_IP_PER_MIN: int = int(os.getenv("INGEST_MAX_REQUESTS_PER_IP_PER_MIN", "1200"))
    # Hard cap on stored chunks per page visit (protects the merge step).
    INGEST_MAX_CHUNKS_PER_SESSION: int = int(os.getenv("INGEST_MAX_CHUNKS_PER_SESSION", "2000"))
    # Only trust X-Forwarded-For when running behind a known reverse proxy.
    TRUST_PROXY_HEADERS: bool = os.getenv("TRUST_PROXY_HEADERS", "False").lower() in ("true", "1")

    # External Agent configuration (optional — app works without these)
    AGENT_PROVIDER: str = os.getenv("AGENT_PROVIDER", "")
    AGENT_MODEL: str = os.getenv("AGENT_MODEL", "")
    AGENT_API_KEY: str = os.getenv("AGENT_API_KEY", "")


settings = Settings()
