"""
Global pytest configuration and fixtures for WebSense test suite.

Provides an isolated temporary database for the test run so tests do not depend
on or mutate developer/demo database files.
"""

import os
import tempfile
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

import packages.database.db as db_module
from packages.database.models import SiteRecord, Base
from apps.api.main import app
from apps.api.config import settings
from apps.api.routes.sessions import _session_limiter, _ip_limiter


@pytest.fixture(scope="session")
def test_db_path():
    """Creates a temporary sqlite file for the test session."""
    fd, path = tempfile.mkstemp(prefix="websense_test_", suffix=".db")
    os.close(fd)
    yield path
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


@pytest.fixture(scope="session", autouse=True)
def setup_test_database(test_db_path):
    """Sets up a clean database schema and seeds default sites for tests."""
    engine = create_engine(
        f"sqlite:///{test_db_path}",
        connect_args={"check_same_thread": False},
        echo=False
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Patch the global engine & SessionLocal in db_module
    orig_engine = db_module.engine
    orig_sessionlocal = db_module.SessionLocal

    db_module.engine = engine
    db_module.SessionLocal = TestingSessionLocal

    # Create all tables and run additive migrations
    db_module.init_db()

    # Ensure default sites exist
    with TestingSessionLocal() as session:
        default_sites = [
            {
                "site_id": settings.DEFAULT_SITE_ID,
                "name": "Meridian Honey-Suite (Official)",
                "allowed_origins": "*",
                "api_key": "ws_live_meridian_default_key_2026",
                "is_active": True,
            },
            {
                "site_id": settings.EXTENSION_SITE_ID,
                "name": "WebSense Chrome Extension",
                "allowed_origins": "*",
                "api_key": "ws_live_chrome_ext_default_key",
                "is_active": True,
            },
        ]
        for s_data in default_sites:
            if not session.query(SiteRecord).filter_by(site_id=s_data["site_id"]).first():
                session.add(SiteRecord(**s_data))
        session.commit()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[db_module.get_db] = override_get_db

    yield

    app.dependency_overrides.pop(db_module.get_db, None)
    db_module.engine = orig_engine
    db_module.SessionLocal = orig_sessionlocal


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    """Resets in-memory sliding window rate limiters before every test."""
    _session_limiter.reset()
    _ip_limiter.reset()
    yield
    _session_limiter.reset()
    _ip_limiter.reset()


@pytest.fixture(scope="session")
def client(setup_test_database):
    """FastAPI TestClient session-scoped fixture with lifespan context enabled."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session(setup_test_database):
    """Provides an isolated SQLAlchemy session connected to the active test database."""
    session = db_module.SessionLocal()
    try:
        yield session
    finally:
        session.close()
