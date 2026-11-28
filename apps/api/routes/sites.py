"""
Site Management and Registration Endpoints for WebSense SDK.
Allows multi-site isolation, CORS verification, and telemetry segregation.
"""

import html
import uuid
import secrets
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from apps.api.config import settings
from packages.database.db import get_db
from packages.database.models import SiteRecord, SessionRecord
from packages.database.schemas import SiteCreateRequest, SiteResponse, SiteListResponse

router = APIRouter(prefix="/api/v1/sites", tags=["Sites"])


def _resolve_public_origin(request: Optional[Request] = None) -> str:
    """Resolves the deployed SentinelTrace origin used for customer embed snippets."""
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL
    if request is not None:
        if settings.TRUST_PROXY_HEADERS:
            forwarded_host = request.headers.get("x-forwarded-host")
            if forwarded_host:
                proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "https").split(",")[0].strip()
                host = forwarded_host.split(",")[0].strip()
                return f"{proto}://{host}".rstrip("/")
        return str(request.base_url).rstrip("/")
    return "https://your-sentineltrace-origin"


def build_embed_snippet(site_id: str, origin: str, task: str = "general") -> str:
    """Builds a copy-pasteable hosted <script> tag for a registered site."""
    safe_origin = html.escape(origin.rstrip("/"), quote=True)
    safe_site_id = html.escape(site_id, quote=True)
    safe_task = html.escape(task or "general", quote=True)
    return (
        f'<script src="{safe_origin}/sentinel.js" '
        f'data-site-id="{safe_site_id}" '
        f'data-task="{safe_task}" async></script>'
    )


def _site_to_response(site: SiteRecord, total_sessions: int, origin: str) -> SiteResponse:
    """Converts a SiteRecord ORM row into a SiteResponse with an embed snippet."""
    return SiteResponse(
        site_id=site.site_id,
        name=site.name,
        allowed_origins=site.allowed_origins,
        api_key=site.api_key,
        webhook_url=site.webhook_url,
        risk_threshold=site.risk_threshold if site.risk_threshold is not None else 80,
        enforcement_mode=site.enforcement_mode or "monitor",
        is_active=site.is_active,
        created_at=site.created_at.isoformat() if site.created_at else "",
        total_sessions=total_sessions,
        embed_snippet=build_embed_snippet(site.site_id, origin),
    )


@router.post("", response_model=SiteResponse, status_code=status.HTTP_201_CREATED)
def register_site(payload: SiteCreateRequest, request: Request, db: Session = Depends(get_db)):
    """
    Registers a new site for the WebSense embeddable SDK.
    Generates a unique site_id, secret API key, and hosted <script> embed snippet.
    """
    site_id = f"site_{uuid.uuid4().hex[:12]}"
    api_key = f"ws_live_{secrets.token_urlsafe(24)}"

    site = SiteRecord(
        site_id=site_id,
        name=payload.name,
        allowed_origins=payload.allowed_origins.strip(),
        api_key=api_key,
        webhook_url=payload.webhook_url,
        risk_threshold=payload.risk_threshold,
        enforcement_mode=payload.enforcement_mode,
        is_active=True
    )
    db.add(site)
    db.commit()
    db.refresh(site)

    origin = _resolve_public_origin(request)
    return _site_to_response(site, total_sessions=0, origin=origin)


@router.get("", response_model=SiteListResponse)
def list_sites(request: Request, db: Session = Depends(get_db)):
    """
    Lists all registered sites along with aggregated session counts and embed snippets.
    """
    sites = db.query(SiteRecord).order_by(SiteRecord.created_at.desc()).all()
    counts = dict(
        db.query(SessionRecord.site_id, func.count(SessionRecord.session_id))
        .group_by(SessionRecord.site_id)
        .all()
    )
    origin = _resolve_public_origin(request)
    results = [_site_to_response(s, total_sessions=int(counts.get(s.site_id, 0)), origin=origin) for s in sites]
    return SiteListResponse(sites=results)


@router.get("/{site_id}", response_model=SiteResponse)
def get_site(site_id: str, request: Request, db: Session = Depends(get_db)):
    """
    Retrieves details and embed snippet for a specific registered site.
    """
    site = db.query(SiteRecord).filter(SiteRecord.site_id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail=f"Site '{site_id}' not found")

    count = db.query(func.count(SessionRecord.session_id)).filter(SessionRecord.site_id == site.site_id).scalar() or 0
    origin = _resolve_public_origin(request)
    return _site_to_response(site, total_sessions=int(count), origin=origin)
