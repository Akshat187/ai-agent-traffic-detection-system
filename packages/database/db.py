"""
WebSense Database Configuration and Session Management.
Supports both SQLite (local development/demo) and PostgreSQL (production deployment).
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sentineltrace.db")

# For SQLite, enable check_same_thread=False
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency for obtaining database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all database tables and apply incremental schema migrations."""
    import packages.database.models  # noqa: F401 - ensure models are registered
    Base.metadata.create_all(bind=engine)

    # SQLite schema migration for columns added in v1.2.0
    if DATABASE_URL.startswith("sqlite"):
        raw_conn = engine.raw_connection()
        try:
            cursor = raw_conn.cursor()
            cursor.execute("PRAGMA table_info(sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if "site_id" not in columns:
                cursor.execute("ALTER TABLE sessions ADD COLUMN site_id VARCHAR(64)")
            if "data_source" not in columns:
                cursor.execute("ALTER TABLE sessions ADD COLUMN data_source VARCHAR(64) DEFAULT 'realtime_sdk'")
            raw_conn.commit()
            cursor.close()
        except Exception as e:
            pass
        finally:
            raw_conn.close()

