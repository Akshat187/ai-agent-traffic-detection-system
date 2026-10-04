"""
Pydantic v2 Schemas — WebSense Web Interaction Intelligence Platform.
"""

from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


# Identifiers are opaque random strings created by collectors. Restricting the
# alphabet and length keeps them safe for logs, URLs and the VARCHAR(64) columns.
ID_PATTERN = r"^[A-Za-z0-9_\-:.]{1,64}$"

# Accepted task values. Supports canonical site tasks and explicit workflow aliases.
TaskName = Literal[
    "general",
    "shopping",
    "travel",
    "forum",
    "custom",
    "flight_booking",
    "ecommerce_purchase",
    "forum_post",
    "other",
]
_TASK_ALIASES = {
    "community": "forum",
    "forum_post": "forum",
    "ecommerce": "shopping",
    "ecommerce_purchase": "shopping",
    "shop": "shopping",
    "flight_booking": "travel",
    "flights": "travel",
    "other": "custom",
}

# Per-chunk event caps. A delta chunk normally holds ~5 s of events; legacy
# full-blob snapshots are capped at 600 mouse events by the old collectors.
MAX_MOUSE_EVENTS_PER_CHUNK = 5000
MAX_KEYBOARD_EVENTS_PER_CHUNK = 2000
MAX_SCROLL_EVENTS_PER_CHUNK = 2000
MAX_CLICK_EVENTS_PER_CHUNK = 1000
MAX_TASK_ACTIONS_PER_CHUNK = 500

# Unix timestamps below this are seconds, above are milliseconds.
_UNIX_MS_THRESHOLD = 1e11


def normalize_task(value: Any) -> Any:
    """Lower-cases task names and maps legacy aliases; leaves validation to Literal."""
    if value is None:
        return "general"
    if isinstance(value, str):
        v = value.strip().lower()
        return _TASK_ALIASES.get(v, v)
    return value


class MouseEventSchema(BaseModel):
    x: float
    y: float
    t: float  # ms since session start
    type: str = "move"  # move, down, up


class KeyboardEventSchema(BaseModel):
    t: float  # ms since session start
    interval: float = 0.0  # inter-key latency
    hold: float = 0.0      # key hold duration
    is_paste: bool = False


class ScrollEventSchema(BaseModel):
    t: float
    scroll_y: float
    delta_y: float = 0.0


class ClickEventSchema(BaseModel):
    x: float
    y: float
    t: float
    target_category: str = "general"


class BrowserSignalsSchema(BaseModel):
    webdriver: bool = False
    screen_width: int = 1920
    screen_height: int = 1080
    viewport_width: int = 1280
    viewport_height: int = 720
    device_pixel_ratio: float = 1.0
    touch_support: bool = False
    hardware_concurrency: Optional[int] = 4
    platform: Optional[str] = "Win32"
    language: Optional[str] = "en-US"
    user_agent: Optional[str] = ""
    timezone_offset: Optional[int] = 0


class TaskActionSchema(BaseModel):
    action: str
    t: float
    details: Dict[str, Any] = Field(default_factory=dict)


class ClientContextSchema(BaseModel):
    tab_id: str = Field("", max_length=64)
    page_path: str = Field("", max_length=512)
    page_title: str = Field("", max_length=256)
    page_url: str = Field("", max_length=512)
    page_host: str = Field("", max_length=256)
    referrer_path: str = Field("", max_length=512)
    visibility_state: str = Field("visible", max_length=16)
    transmission_seq: int = 1
    sdk_version: str = Field("", max_length=64)
    collector: str = Field("", max_length=16)  # "sdk" | "ext" | "" (legacy)


class SiteCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    allowed_origins: str = Field(default="*", description="Comma-separated allowed domains e.g. https://example.com,http://localhost:3000")


class SiteResponse(BaseModel):
    site_id: str
    name: str
    allowed_origins: str
    api_key: Optional[str] = None
    is_active: bool = True
    created_at: str
    total_sessions: int = 0


class SiteListResponse(BaseModel):
    sites: List[SiteResponse]


class IngestSessionRequest(BaseModel):
    """
    One transmission from a collector.

    Identity model: ``session_id`` identifies ONE page visit (it is the same
    value as ``page_visit_id``). ``journey_id`` groups the page visits of one
    tab, ``tab_id`` (in client_context) is metadata only.

    Protocol v2 (delta): the collector sets ``seq`` (1, 2, 3 … per page visit)
    and sends only the events recorded since the previous chunk. Retries reuse
    the same ``seq``. The server stores each chunk once and rebuilds features
    from all chunks of the visit.

    Legacy (snapshot): ``seq`` is absent and the payload holds ALL events since
    page load. ``client_context.transmission_seq`` (if present) orders snapshots;
    older snapshots are ignored.
    """

    session_id: str = Field(..., pattern=ID_PATTERN)
    site_id: Optional[str] = Field(None, pattern=ID_PATTERN)
    visitor_id: Optional[str] = Field(None, pattern=ID_PATTERN)
    page_visit_id: Optional[str] = Field(None, pattern=ID_PATTERN)
    journey_id: Optional[str] = Field(None, pattern=ID_PATTERN)
    previous_visit_id: Optional[str] = Field(None, pattern=ID_PATTERN)

    task: TaskName = "general"
    custom_task: Optional[str] = Field(None, max_length=64)

    # Delta protocol
    seq: Optional[int] = Field(None, ge=1, le=1_000_000)
    final: bool = False  # last chunk of this page visit (pagehide / route change)

    start_time: float  # Unix epoch, milliseconds (seconds are auto-converted)
    end_time: float
    duration_ms: float = Field(0.0, ge=0)
    # Engaged time on the page: excludes hidden-tab time and idle gaps > 60 s.
    active_duration_ms: Optional[float] = Field(None, ge=0)

    ground_truth_label: Optional[str] = None  # Optional for synthetic generation
    is_synthetic: bool = False
    data_source: str = Field("realtime_sdk", max_length=64)
    client_context: Optional[ClientContextSchema] = None

    browser_signals: BrowserSignalsSchema = Field(default_factory=BrowserSignalsSchema)
    mouse_events: List[MouseEventSchema] = Field(default_factory=list, max_length=MAX_MOUSE_EVENTS_PER_CHUNK)
    keyboard_events: List[KeyboardEventSchema] = Field(default_factory=list, max_length=MAX_KEYBOARD_EVENTS_PER_CHUNK)
    scroll_events: List[ScrollEventSchema] = Field(default_factory=list, max_length=MAX_SCROLL_EVENTS_PER_CHUNK)
    click_events: List[ClickEventSchema] = Field(default_factory=list, max_length=MAX_CLICK_EVENTS_PER_CHUNK)
    task_actions: List[TaskActionSchema] = Field(default_factory=list, max_length=MAX_TASK_ACTIONS_PER_CHUNK)

    @field_validator("task", mode="before")
    @classmethod
    def _normalize_task(cls, v: Any) -> Any:
        return normalize_task(v)

    @model_validator(mode="after")
    def _normalize(self) -> "IngestSessionRequest":
        # page_visit_id is an alias of session_id; they must agree when both are sent.
        if self.page_visit_id and self.page_visit_id != self.session_id:
            raise ValueError("page_visit_id must equal session_id")
        # Always store milliseconds. Legacy sentinel.js sent Unix seconds.
        if 0 < self.start_time < _UNIX_MS_THRESHOLD:
            self.start_time *= 1000.0
        if 0 < self.end_time < _UNIX_MS_THRESHOLD:
            self.end_time *= 1000.0
        if self.task != "custom":
            self.custom_task = None
        return self

    @property
    def is_delta(self) -> bool:
        return self.seq is not None


class ClassificationResponse(BaseModel):
    session_id: str
    predicted_label: str  # HUMAN, TRADITIONAL_AUTOMATION, AGENTIC_AI, UNCERTAIN
    confidence: float
    risk_score: float
    l1_rule_score: float
    l2_ml_pred: str
    l3_is_anomaly: bool
    l4_is_replay: bool
    l5_context_valid: bool
    contributing_signals: List[str]
    counter_signals: List[str]
    human_explanation: str
    model_version: str
    # Layer 5 status: "valid" | "violated" | "not_applicable"
    l5_status: str = "not_applicable"
    active_duration_ms: Optional[float] = None
    # Ingest protocol outcome
    page_visit_id: Optional[str] = None
    seq: Optional[int] = None
    last_seq: int = 0
    duplicate: bool = False   # this seq was already stored; nothing was written
    stale: bool = False       # legacy snapshot older than the stored one; ignored
    gap: bool = False         # seq skipped ahead (missing chunks may still arrive)


class SessionSummary(BaseModel):
    session_id: str
    site_id: Optional[str] = None
    visitor_id: Optional[str]
    task: str
    start_time: float
    duration_ms: float
    data_source: str = "realtime_sdk"
    ground_truth_label: Optional[str]
    predicted_label: str
    confidence: float
    risk_score: float
    is_synthetic: bool
    created_at: str
    webdriver_flag: bool
    explanation_snippet: str
    tab_id: Optional[str] = None
    page_path: Optional[str] = None
    page_title: Optional[str] = None
    transmission_seq: Optional[int] = None
    client_context: Optional[Dict[str, Any]] = None
    data_quality: str = "standard"
    # Page-visit identity (session_id == page_visit_id)
    page_visit_id: Optional[str] = None
    journey_id: Optional[str] = None
    previous_visit_id: Optional[str] = None
    page_url: Optional[str] = None
    custom_task: Optional[str] = None
    last_seq: int = 0
    active_duration_ms: Optional[float] = None
    updated_at: Optional[str] = None


class SessionDetailResponse(BaseModel):
    session: SessionSummary
    features: Dict[str, Any]
    verdict: Dict[str, Any]
    telemetry: Dict[str, Any]


class OverviewStatsResponse(BaseModel):
    total_sessions: int
    human_count: int
    human_pct: float
    bot_count: int = 0
    bot_pct: float = 0.0
    automation_count: int = 0
    automation_pct: float = 0.0
    ai_agent_count: int = 0
    ai_agent_pct: float = 0.0
    traditional_automation_count: int = 0
    traditional_automation_pct: float = 0.0
    agentic_ai_count: int = 0
    agentic_ai_pct: float = 0.0
    agentic_count: int = 0
    agentic_pct: float = 0.0
    uncertain_count: int = 0
    uncertain_pct: float = 0.0
    mean_confidence: float = 0.0
    mean_risk_score: float = 0.0
    avg_confidence: float = 0.0
    avg_risk_score: float = 0.0
    recent_activity: List[SessionSummary] = Field(default_factory=list)
    detection_timeline: List[Dict[str, Any]] = Field(default_factory=list)
    low_signal_count: int = 0
