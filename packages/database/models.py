"""
SQLAlchemy Database Models for WebSense.
Schema v1.1 — separates raw telemetry, derived features, predictions, ground truth, and experiment metadata.
"""

from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    JSON,
)
from sqlalchemy.orm import relationship
from packages.database.db import Base


class SiteRecord(Base):
    """
    Registered client site using the WebSense embeddable SDK.
    Enforces origin verification and segregates multi-site analytics.
    """

    __tablename__ = "sites"

    site_id = Column(String(64), primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    allowed_origins = Column(String(512), default="*")  # Comma-separated domains e.g. "https://example.com,http://localhost:3000"
    api_key = Column(String(64), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    sessions = relationship("SessionRecord", back_populates="site", cascade="all, delete-orphan")


class SessionRecord(Base):
    """
    Core session record. One row per detected interaction session.
    data_source: 'realtime_sdk' | 'synthetic_demo' | 'synthetic_test' |
                 'synthetic_simulated_agent' | 'synthetic_bot'
    """

    __tablename__ = "sessions"

    session_id = Column(String(64), primary_key=True, index=True)
    site_id = Column(String(64), ForeignKey("sites.site_id"), index=True, nullable=True)
    visitor_id = Column(String(64), index=True, nullable=True)

    # Task must be one of: shopping / travel / community / custom
    task = Column(String(64), default="shopping", index=True)

    start_time = Column(Float, nullable=True)
    end_time = Column(Float, nullable=True)
    duration_ms = Column(Float, default=0.0)
    user_agent = Column(String(512), nullable=True)
    ip_hash = Column(String(64), nullable=True)

    # Provenance — always set so dashboard can label DEMO DATA vs LIVE SDK clearly
    data_source = Column(String(64), default="realtime_sdk", index=True)

    # Ground truth (only set for synthetic/experiment sessions)
    ground_truth_label = Column(String(32), nullable=True, index=True)
    is_synthetic = Column(Boolean, default=False)

    # Final classification
    predicted_label = Column(String(32), default="UNCERTAIN", index=True)
    confidence = Column(Float, default=0.0)
    risk_score = Column(Float, default=0.0)

    # Versioning — every prediction records which model produced it
    model_version = Column(String(64), default="v1.1.0-defense-in-depth")
    feature_schema_version = Column(String(16), default="v1.1")

    # Tab / page identification metadata from client_context
    tab_id = Column(String(64), index=True, nullable=True)
    page_path = Column(String(256), nullable=True)
    page_title = Column(String(256), nullable=True)
    transmission_seq = Column(Integer, default=1)
    client_context = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    # Data quality flag: 'standard' | 'low_signal' (e.g. near-empty sessions with insufficient events)
    data_quality = Column(String(32), default="standard", index=True)

    # Relationships
    site = relationship("SiteRecord", back_populates="sessions")
    telemetry = relationship(
        "RawTelemetry", back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    features = relationship(
        "FeatureRecord", back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    verdict = relationship(
        "DetectionVerdict", back_populates="session", uselist=False, cascade="all, delete-orphan"
    )


class RawTelemetry(Base):
    """
    Raw client-side telemetry.  Keyboard events store ONLY timing metadata —
    never character content, never passwords.
    """

    __tablename__ = "raw_telemetry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), ForeignKey("sessions.session_id"), unique=True, index=True)

    mouse_events = Column(JSON, nullable=True)     # [{x, y, t, type}, ...]
    keyboard_events = Column(JSON, nullable=True)  # [{t, interval, hold, is_paste}, ...] NO CHARACTERS
    scroll_events = Column(JSON, nullable=True)    # [{t, scroll_y, delta_y}, ...]
    click_events = Column(JSON, nullable=True)     # [{x, y, t, target_category}, ...]
    browser_signals = Column(JSON, nullable=True)  # {webdriver, screen_w, screen_h, ...}
    task_actions = Column(JSON, nullable=True)     # [{action, t, details}, ...]

    session = relationship("SessionRecord", back_populates="telemetry")


class FeatureRecord(Base):
    """
    Extracted numerical behavioral features.  These are the inputs to the ML classifier.
    Separating features from raw telemetry allows recomputation without re-ingestion.
    """

    __tablename__ = "features"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), ForeignKey("sessions.session_id"), unique=True, index=True)

    # Mouse kinematics
    mouse_mean_velocity = Column(Float, default=0.0)
    mouse_velocity_std = Column(Float, default=0.0)
    mouse_acceleration_std = Column(Float, default=0.0)
    mouse_jerk_mean = Column(Float, default=0.0)
    mouse_straightness_ratio = Column(Float, default=1.0)
    mouse_micro_corrections = Column(Integer, default=0)
    mouse_direction_changes = Column(Integer, default=0)
    mouse_pause_ratio = Column(Float, default=0.0)
    mouse_low_speed_ratio = Column(Float, default=0.0)

    # Keyboard timing (NO character content)
    key_mean_latency = Column(Float, default=0.0)
    key_latency_std = Column(Float, default=0.0)
    key_latency_cv = Column(Float, default=0.0)   # CV = std/mean; bots → near 0
    key_mean_hold_time = Column(Float, default=0.0)
    key_paste_count = Column(Integer, default=0)

    # Scroll dynamics
    scroll_velocity_mean = Column(Float, default=0.0)
    scroll_velocity_std = Column(Float, default=0.0)
    scroll_discrete_jump_ratio = Column(Float, default=0.0)

    # Interaction timing
    interaction_first_action_delay = Column(Float, default=0.0)
    interaction_click_interval_std = Column(Float, default=0.0)
    interaction_density = Column(Float, default=0.0)

    # Browser environment
    webdriver_flag = Column(Boolean, default=False)

    # Full feature vector (JSON) for ML and ablation experiments
    all_features_json = Column(JSON, nullable=True)

    session = relationship("SessionRecord", back_populates="features")


class DetectionVerdict(Base):
    """
    Layer-by-layer detection results and explainability output.
    """

    __tablename__ = "detection_verdicts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), ForeignKey("sessions.session_id"), unique=True, index=True)

    # Layer 1: Rules
    l1_rule_score = Column(Float, default=0.0)
    l1_flags = Column(JSON, default=list)

    # Layer 2: Behavioral ML
    l2_ml_pred = Column(String(32), default="UNCERTAIN")
    l2_ml_confidence = Column(Float, default=0.0)
    l2_ml_probabilities = Column(JSON, default=dict)

    # Layer 3: Anomaly Detection
    l3_anomaly_score = Column(Float, default=0.0)
    l3_is_anomaly = Column(Boolean, default=False)

    # Layer 4: Trajectory Replay Defense
    l4_replay_similarity = Column(Float, default=0.0)
    l4_matched_session_id = Column(String(64), nullable=True)
    l4_is_replay = Column(Boolean, default=False)

    # Layer 5: Contextual Validation
    l5_context_valid = Column(Boolean, default=True)
    l5_context_violations = Column(JSON, default=list)

    # Unified decision
    final_verdict = Column(String(32), default="UNCERTAIN")
    confidence = Column(Float, default=0.0)
    risk_score = Column(Float, default=0.0)

    # Explainability
    contributing_signals = Column(JSON, default=list)
    counter_signals = Column(JSON, default=list)
    human_explanation = Column(Text, default="")
    model_version = Column(String(64), default="v1.1.0-defense-in-depth")

    session = relationship("SessionRecord", back_populates="verdict")


class ExperimentRecord(Base):
    """
    Stores metadata and metrics from each experiment run.
    Every field required for full reproducibility.
    """

    __tablename__ = "experiment_records"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), index=True)
    description = Column(Text, nullable=True)

    # Reproducibility fields
    dataset_version = Column(String(64), nullable=True)   # hash/label of dataset used
    random_seed = Column(Integer, default=42)
    training_config = Column(JSON, default=dict)          # model hyperparameters
    feature_set = Column(String(64))                      # browser_only / mouse_only / combined / etc.

    # Model info
    model_name = Column(String(64))
    model_version = Column(String(64), default="v1.1.0")

    # Metrics — all computed from REAL evaluation, never hardcoded
    accuracy = Column(Float, default=0.0)
    precision_macro = Column(Float, default=0.0)
    recall_macro = Column(Float, default=0.0)
    f1_macro = Column(Float, default=0.0)
    per_class_metrics = Column(JSON, default=dict)
    confusion_matrix = Column(JSON, default=list)
    feature_importance = Column(JSON, default=list)

    sample_size = Column(Integer, default=0)
    train_size = Column(Integer, default=0)
    test_size = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, nullable=True)

