"""
WebSense — Web Interaction Intelligence Platform
FastAPI Application Entrypoint.
Serves REST API, static assets, and web honey-site experiences.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from packages.database.db import init_db, SessionLocal
from packages.database.models import SessionRecord, SiteRecord
from apps.api.config import settings
from apps.api.routes import sessions, stats, experiments, adversarial, seed, sites

# Setup base directories
BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = BASE_DIR / "apps" / "web" / "public"
TEMPLATES_DIR = BASE_DIR / "apps" / "web" / "templates"


def _migrate_legacy_labels(db) -> int:
    """
    Migrates legacy class labels to new actor terminology.
    BOT → TRADITIONAL_AUTOMATION
    AI_AGENT → AGENTIC_AI
    """
    migrated = 0
    label_map = {
        "BOT": "TRADITIONAL_AUTOMATION",
        "AI_AGENT": "AGENTIC_AI",
    }
    for old_label, new_label in label_map.items():
        result = db.query(SessionRecord).filter(
            SessionRecord.predicted_label == old_label
        ).all()
        for session in result:
            session.predicted_label = new_label
            migrated += 1

        result_gt = db.query(SessionRecord).filter(
            SessionRecord.ground_truth_label == old_label
        ).all()
        for session in result_gt:
            session.ground_truth_label = new_label
            migrated += 1

    if migrated > 0:
        db.commit()
    return migrated


def _ensure_default_sites(db):
    """Provisions default sites if not already present."""
    default_site = db.query(SiteRecord).filter(SiteRecord.site_id == "site_meridian_prod").first()
    if not default_site:
        site = SiteRecord(
            site_id="site_meridian_prod",
            name="Meridian Honey-Suite (Official)",
            allowed_origins="*",
            api_key="ws_live_meridian_default_key_2026",
            is_active=True
        )
        db.add(site)
        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initializes database on startup.
    Runs label migration and provisions default sites.
    Seeds minimal demo data if the database is empty.
    """
    init_db()
    db = SessionLocal()
    try:
        # Phase 1: Migrate any legacy labels
        migrated = _migrate_legacy_labels(db)
        if migrated > 0:
            print(f"[WebSense] Label migration complete — {migrated} rows updated.")

        # Phase 2: Ensure default sites exist
        _ensure_default_sites(db)

        # Phase 3: Seed demo data if database is empty
        count = db.query(SessionRecord).count()
        if count == 0:
            from apps.api.dependencies import detection_engine
            seed.seed_demo_data(count_per_class=10, db=db, engine=detection_engine)
            print("[WebSense] Demo dataset seeded.")
    finally:
        db.close()
    yield


# Initialize FastAPI App
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Web Interaction Intelligence Platform — classifies sessions into Human, Traditional Automation, Agentic AI, and Uncertain.",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS Middleware (Supports external embedded sites)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Static Files & Templates
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Include API Routers
app.include_router(sessions.router)
app.include_router(stats.router)
app.include_router(experiments.router)
app.include_router(adversarial.router)
app.include_router(seed.router)
app.include_router(sites.router)


# Direct SDK Script Endpoint
@app.get("/sentinel.js", tags=["SDK"])
def get_sentinel_script():
    """Serves the standalone embeddable Sentinel SDK directly from root."""
    js_path = STATIC_DIR / "sentinel.js"
    if not js_path.exists():
        js_path = STATIC_DIR / "collector.js"
    return FileResponse(js_path, media_type="application/javascript")


# Health Check Endpoints
@app.get("/healthz", tags=["Health"])
def health_check():
    """Liveness health check."""
    return {"status": "healthy", "service": "WebSense API", "version": settings.APP_VERSION}


@app.get("/readyz", tags=["Health"])
def readiness_check():
    """Readiness probe."""
    return {"status": "ready", "database": "connected"}


# Web Page Routes
@app.get("/", response_class=HTMLResponse, tags=["Web"])
def root():
    """Redirect root to the WebSense dashboard."""
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard", response_class=HTMLResponse, tags=["Web"])
def render_dashboard(request: Request):
    """Renders the WebSense Behavioral Intelligence Dashboard."""
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"request": request})


@app.get("/visitor", response_class=HTMLResponse, tags=["Web"])
def render_visitor_home(request: Request):
    """Renders the Meridian interaction suite landing page."""
    return templates.TemplateResponse(request=request, name="visitor_home.html", context={"request": request})


@app.get("/visitor/shop", response_class=HTMLResponse, tags=["Web"])
def render_visitor_shop(request: Request):
    """Renders the Shopping behavioral collection site."""
    return templates.TemplateResponse(request=request, name="visitor_shop.html", context={"request": request})


@app.get("/visitor/travel", response_class=HTMLResponse, tags=["Web"])
def render_visitor_travel(request: Request):
    """Renders the Travel Booking behavioral collection site."""
    return templates.TemplateResponse(request=request, name="visitor_travel.html", context={"request": request})


@app.get("/visitor/forum", response_class=HTMLResponse, tags=["Web"])
def render_visitor_forum(request: Request):
    """Renders the Community Forum behavioral collection site."""
    return templates.TemplateResponse(request=request, name="visitor_forum.html", context={"request": request})


@app.get("/visitor/community", response_class=HTMLResponse, tags=["Web"])
def render_visitor_community(request: Request):
    """Alias for Community Forum behavioral collection site."""
    return templates.TemplateResponse(request=request, name="visitor_forum.html", context={"request": request})


@app.get("/standalone_demo", response_class=HTMLResponse, tags=["Web"])
def render_standalone_demo(request: Request):
    """Renders external embedded test demo page."""
    return templates.TemplateResponse(request=request, name="standalone_demo.html", context={"request": request})

