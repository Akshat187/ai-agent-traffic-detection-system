"""
Pydantic v2 Schemas — WebSense Web Interaction Intelligence Platform.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


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
    tab_id: str
    page_path: str = ""
    page_title: str = ""
    page_url: str = ""
    referrer_path: str = ""
    visibility_state: str = "visible"
    transmission_seq: int = 1
    sdk_version: str = ""


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
    session_id: str
    site_id: Optional[str] = None
    visitor_id: Optional[str] = None
    task: str = "shopping"
    start_time: float
    end_time: float
    duration_ms: float = 0.0
    ground_truth_label: Optional[str] = None  # Optional for synthetic generation
    is_synthetic: bool = False
    data_source: str = "realtime_sdk"
    client_context: Optional[ClientContextSchema] = None

    browser_signals: BrowserSignalsSchema = Field(default_factory=BrowserSignalsSchema)
    mouse_events: List[MouseEventSchema] = Field(default_factory=list)
    keyboard_events: List[KeyboardEventSchema] = Field(default_factory=list)
    scroll_events: List[ScrollEventSchema] = Field(default_factory=list)
    click_events: List[ClickEventSchema] = Field(default_factory=list)
    task_actions: List[TaskActionSchema] = Field(default_factory=list)


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
