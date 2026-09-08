"""
Site Management and Registration Endpoints for WebSense SDK.
Allows multi-site isolation, CORS verification, and telemetry segregation.
"""

import uuid
import secrets
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from packages.database.db import get_db
from packages.database.models import SiteRecord, SessionRecord
from packages.database.schemas import SiteCreateRequest, SiteResponse, SiteListResponse

router = APIRouter(prefix="/api/v1/sites", tags=["Sites"])


@router.post("", response_model=SiteResponse, status_code=status.HTTP_201_CREATED)
def register_site(payload: SiteCreateRequest, db: Session = Depends(get_db)):
    """
    Registers a new site for the WebSense embeddable SDK.
    Generates a unique site_id and secret API key.
    """
    site_id = f"site_{uuid.uuid4().hex[:12]}"
    api_key = f"ws_live_{secrets.token_urlsafe(24)}"

    site = SiteRecord(
        site_id=site_id,
        name=payload.name,
        allowed_origins=payload.allowed_origins.strip(),
        api_key=api_key,
        is_active=True
    )
    db.add(site)
    db.commit()
    db.refresh(site)

    return SiteResponse(
        site_id=site.site_id,
        name=site.name,
        allowed_origins=site.allowed_origins,
        api_key=site.api_key,
        is_active=site.is_active,
        created_at=site.created_at.isoformat() if site.created_at else "",
        total_sessions=0
    )


@router.get("", response_model=SiteListResponse)
def list_sites(db: Session = Depends(get_db)):
    """
    Lists all registered sites along with aggregated session counts.
    """
    sites = db.query(SiteRecord).order_by(SiteRecord.created_at.desc()).all()
    results = []

    for s in sites:
        count = db.query(func.count(SessionRecord.session_id)).filter(SessionRecord.site_id == s.site_id).scalar() or 0
        results.append(SiteResponse(
            site_id=s.site_id,
            name=s.name,
            allowed_origins=s.allowed_origins,
            api_key=s.api_key,
            is_active=s.is_active,
            created_at=s.created_at.isoformat() if s.created_at else "",
            total_sessions=count
        ))

    return SiteListResponse(sites=results)


@router.get("/{site_id}", response_model=SiteResponse)
def get_site(site_id: str, db: Session = Depends(get_db)):
    """
    Retrieves details for a specific registered site.
    """
    site = db.query(SiteRecord).filter(SiteRecord.site_id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail=f"Site '{site_id}' not found")

    count = db.query(func.count(SessionRecord.session_id)).filter(SessionRecord.site_id == site.site_id).scalar() or 0

    return SiteResponse(
        site_id=site.site_id,
        name=site.name,
        allowed_origins=site.allowed_origins,
        api_key=site.api_key,
        is_active=site.is_active,
        created_at=site.created_at.isoformat() if site.created_at else "",
        total_sessions=count
    )
