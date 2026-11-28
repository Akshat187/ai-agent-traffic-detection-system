"""
Integration tests for Embeddable SDK, Site Registration, CORS Origin Verification,
and Multi-Site Telemetry Pipeline.
"""

import uuid
import pytest
from fastapi.testclient import TestClient
from apps.api.main import app
from packages.database.db import get_db, SessionLocal
from packages.database.models import SiteRecord, SessionRecord


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_sentinel_script_endpoint(client):
    """Verifies that /sentinel.js is served cross-origin with explicit cache headers."""
    resp = client.get("/sentinel.js")
    assert resp.status_code == 200
    assert "application/javascript" in resp.headers["content-type"]
    assert "Sentinel Behavioral Intelligence SDK" in resp.text
    assert resp.headers.get("access-control-allow-origin") == "*"
    assert resp.headers.get("cross-origin-resource-policy") == "cross-origin"
    assert resp.headers.get("x-content-type-options") == "nosniff"
    cache_ctrl = resp.headers.get("cache-control", "")
    assert "public" in cache_ctrl
    assert "max-age=3600" in cache_ctrl

    # Cross-origin fetch and HEAD/OPTIONS preflight support
    cors_get = client.get("/sentinel.js", headers={"Origin": "https://customer-store.example"})
    assert cors_get.status_code == 200
    assert cors_get.headers.get("access-control-allow-origin") in ("*", "https://customer-store.example")

    head_resp = client.head("/sentinel.js")
    assert head_resp.status_code == 200
    assert "max-age=3600" in head_resp.headers.get("cache-control", "")

    opt_resp = client.options("/sentinel.js")
    assert opt_resp.status_code in (200, 204)
    assert opt_resp.headers.get("access-control-allow-origin") == "*"


def test_site_registration_lifecycle(client, monkeypatch):
    """Tests registering a new site, embed_snippet output, listing, and detail lookup."""
    payload = {
        "name": "E-Commerce External Partner",
        "allowed_origins": "https://partner-shop.com,https://staging.partner-shop.com"
    }
    resp = client.post("/api/v1/sites", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["site_id"].startswith("site_")
    assert data["name"] == payload["name"]
    assert "https://partner-shop.com" in data["allowed_origins"]
    assert data["api_key"].startswith("ws_live_")
    assert "/sentinel.js" in data["embed_snippet"]
    assert f'data-site-id="{data["site_id"]}"' in data["embed_snippet"]
    assert "<script " in data["embed_snippet"] and "</script>" in data["embed_snippet"]

    site_id = data["site_id"]

    # Verify list
    list_resp = client.get("/api/v1/sites")
    assert list_resp.status_code == 200
    sites = list_resp.json()["sites"]
    matched = [s for s in sites if s["site_id"] == site_id]
    assert len(matched) == 1
    assert f'data-site-id="{site_id}"' in matched[0]["embed_snippet"]

    # Verify get by ID and PUBLIC_BASE_URL override
    from apps.api.config import settings
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://detect.example.com")
    get_resp = client.get(f"/api/v1/sites/{site_id}")
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["site_id"] == site_id
    assert 'src="https://detect.example.com/sentinel.js"' in get_data["embed_snippet"]


def test_dashboard_includes_site_registration_and_snippet_panel(client):
    """Verifies /dashboard exposes the Sites & Embed tab and copy-paste snippet controls."""
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "tab-sites" in resp.text
    assert "register-site-form" in resp.text
    assert "install-snippet-code" in resp.text
    assert "copy-snippet-btn" in resp.text


def test_telemetry_ingestion_with_valid_site_origin(client):
    """Tests session ingestion from an authorized origin for a registered site."""
    # 1. Register a restricted site
    reg_resp = client.post("/api/v1/sites", json={
        "name": "Origin Test Site",
        "allowed_origins": "https://secure-store.com"
    })
    site_id = reg_resp.json()["site_id"]

    import uuid
    sess_id = f"test_valid_origin_{uuid.uuid4().hex[:8]}"
    telemetry_payload = {
        "session_id": sess_id,
        "site_id": site_id,
        "task": "shopping",
        "start_time": 1700000000.0,
        "end_time": 1700000010.0,
        "duration_ms": 10000.0,
        "data_source": "realtime_sdk",
        "browser_signals": {
            "webdriver": False,
            "screen_width": 1920,
            "screen_height": 1080
        },
        "mouse_events": [
            {"x": 100, "y": 100, "t": 100, "type": "move"},
            {"x": 120, "y": 125, "t": 200, "type": "move"},
            {"x": 150, "y": 160, "t": 350, "type": "move"},
            {"x": 200, "y": 210, "t": 550, "type": "move"}
        ],
        "keyboard_events": [
            {"t": 600, "interval": 120.0, "hold": 65.0, "is_paste": False}
        ],
        "scroll_events": [
            {"t": 800, "scroll_y": 100, "delta_y": 100}
        ],
        "click_events": [
            {"x": 200, "y": 210, "t": 900, "target_category": "button"}
        ],
        "task_actions": [
            {"action": "add_to_cart", "t": 950, "details": {"product_id": "prod_linen_throw"}}
        ]
    }

    headers = {"Origin": "https://secure-store.com"}
    resp = client.post("/api/v1/sessions", json=telemetry_payload, headers=headers)
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["session_id"] == telemetry_payload["session_id"]
    assert res_data["predicted_label"] in ["HUMAN", "TRADITIONAL_AUTOMATION", "AGENTIC_AI", "UNCERTAIN"]

    # 3. Verify session persisted with site_id
    sess_resp = client.get(f"/api/v1/sessions/{telemetry_payload['session_id']}")
    assert sess_resp.status_code == 200
    summary = sess_resp.json()["session"]
    assert summary["site_id"] == site_id
    assert summary["data_source"] == "realtime_sdk"


def test_telemetry_ingestion_with_forbidden_origin(client):
    """Tests that telemetry from an unauthorized origin is rejected with 403."""
    reg_resp = client.post("/api/v1/sites", json={
        "name": "Restricted Domain Site",
        "allowed_origins": "https://allowed-only.com"
    })
    site_id = reg_resp.json()["site_id"]

    sess_id = f"test_forbidden_{uuid.uuid4().hex[:8]}"
    telemetry_payload = {
        "session_id": sess_id,
        "site_id": site_id,
        "task": "shopping",
        "start_time": 1700000000.0,
        "end_time": 1700000005.0,
        "duration_ms": 5000.0,
        "data_source": "realtime_sdk",
        "browser_signals": {"webdriver": False},
        "mouse_events": [{"x": 50, "y": 50, "t": 50, "type": "move"}],
        "keyboard_events": [],
        "scroll_events": [],
        "click_events": [],
        "task_actions": []
    }

    headers = {"Origin": "https://malicious-site.com"}
    resp = client.post("/api/v1/sessions", json=telemetry_payload, headers=headers)
    assert resp.status_code == 403
    assert "not authorized" in resp.json()["detail"]


def test_multi_site_stats_and_session_filtering(client):
    """Tests filtering sessions and stats by site_id."""
    # Filter sessions by default site
    resp_all = client.get("/api/v1/sessions?limit=50")
    assert resp_all.status_code == 200

    resp_site = client.get("/api/v1/sessions?site_id=site_meridian_prod&limit=50")
    assert resp_site.status_code == 200

    # Filter stats by site_id
    stats_all = client.get("/api/v1/stats/overview")
    assert stats_all.status_code == 200
    assert "total_sessions" in stats_all.json()

    stats_site = client.get("/api/v1/stats/overview?site_id=site_meridian_prod")
    assert stats_site.status_code == 200
    assert "total_sessions" in stats_site.json()
