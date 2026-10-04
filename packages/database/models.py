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
    Index,
    PrimaryKeyConstraint,
)
from sqlalchemy.orm import relationship
from packages.database.db import Base
from packages.version import MODEL_VERSION, FEATURE_SCHEMA_VERSION


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
    Core session record. ONE ROW PER PAGE VISIT (session_id == page_visit_id).
    journey_id groups the page visits of one tab; tab_id is metadata only.
    data_source: 'realtime_sdk' | 'chrome_extension' | 'synthetic_demo' | ...
    """

    __tablename__ = "sessions"

    session_id = Column(String(64), primary_key=True, index=True)
    site_id = Column(String(64), ForeignKey("sites.site_id"), index=True, nullable=True)
    visitor_id = Column(String(64), index=True, nullable=True)

    # general | shopping | travel | forum | custom  (validated at ingest)
    task = Column(String(64), default="general", index=True)
    custom_task = Column(String(64), nullable=True)

    # Unix epoch milliseconds (ingest normalizes legacy seconds)
    start_time = Column(Float, nullable=True)
    end_time = Column(Float, nullable=True)
    duration_ms = Column(Float, default=0.0)
    active_ms = Column(Float, nullable=True)  # engaged time reported by the collector
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
    model_version = Column(String(64), default=MODEL_VERSION)
    feature_schema_version = Column(String(16), default=FEATURE_SCHEMA_VERSION)

    # Page-visit identity
    journey_id = Column(String(64), index=True, nullable=True)
    previous_visit_id = Column(String(64), nullable=True)
    page_url = Column(String(512), nullable=True)

    # Tab / page identification metadata from client_context
    tab_id = Column(String(64), index=True, nullable=True)
    page_path = Column(String(256), nullable=True)
    page_title = Column(String(256), nullable=True)
    transmission_seq = Column(Integer, default=1)  # kept for API compat; == last_seq
    client_context = Column(JSON, nullable=True)

    # Ingest protocol state: highest accepted seq for this page visit
    last_seq = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, index=True)
    # Data quality flag: 'standard' | 'low_signal' (e.g. near-empty sessions with insufficient events)
    data_quality = Column(String(32), default="standard", index=True)

    @property
    def page_visit_id(self) -> str:
        return self.session_id

    @property
    def is_final(self) -> bool:
        return any(bool(c.is_final) for c in self.chunks)

    __table_args__ = (
        Index("ix_sessions_site_visitor_start", "site_id", "visitor_id", "start_time"),
        Index("ix_sessions_site_page", "site_id", "page_path"),
    )

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
    chunks = relationship(
        "TelemetryChunk", back_populates="session", cascade="all, delete-orphan",
        order_by="TelemetryChunk.seq", lazy="dynamic",
    )
    verdict_history = relationship(
        "VerdictHistory", back_populates="session", cascade="all, delete-orphan",
        order_by="VerdictHistory.seq", lazy="dynamic",
    )


class TelemetryChunk(Base):
    """
    One accepted transmission for a page visit. (session_id, seq) is unique, which
    makes ingest idempotent: a retried chunk can never be stored twice.

    kind: 'delta'    — events recorded since the previous chunk (protocol v2)
          'snapshot' — all events since page load (legacy collectors)
    payload holds the privacy-filtered event lists + browser_signals.
    """

    __tablename__ = "telemetry_chunks"

    session_id = Column(String(64), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    seq = Column(Integer, nullable=False)
    kind = Column(String(16), nullable=False, default="delta")
    is_final = Column(Boolean, default=False)
    event_count = Column(Integer, default=0)
    received_at = Column(DateTime, default=datetime.utcnow)
    payload = Column(JSON, nullable=True)

    __table_args__ = (PrimaryKeyConstraint("session_id", "seq", name="pk_telemetry_chunks"),)

    session = relationship("SessionRecord", back_populates="chunks")

    @property
    def final(self) -> bool:
        return bool(self.is_final)


class VerdictHistory(Base):
    """Verdict after each accepted chunk — gives the per-visit confidence timeline."""

    __tablename__ = "verdict_history"

    session_id = Column(String(64), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    seq = Column(Integer, nullable=False)
    label = Column(String(32))
    confidence = Column(Float, default=0.0)
    risk_score = Column(Float, default=0.0)
    event_count = Column(Integer, default=0)
    evidence = Column(JSON, nullable=True)  # {contributing: [...], counter: [...], l5_status}
    model_version = Column(String(64), default=MODEL_VERSION)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (PrimaryKeyConstraint("session_id", "seq", name="pk_verdict_history"),)

    session = relationship("SessionRecord", back_populates="verdict_history")


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
    l5_status = Column(String(16), default="not_applicable")  # valid | violated | not_applicable

    # Unified decision
    final_verdict = Column(String(32), default="UNCERTAIN")
    confidence = Column(Float, default=0.0)
    risk_score = Column(Float, default=0.0)

    # Explainability
    contributing_signals = Column(JSON, default=list)
    counter_signals = Column(JSON, default=list)
    human_explanation = Column(Text, default="")
    model_version = Column(String(64), default=MODEL_VERSION)

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

