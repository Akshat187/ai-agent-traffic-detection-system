"""
WebSense Database Configuration and Session Management.
Supports both SQLite (local development/demo) and PostgreSQL (production deployment).
"""

import logging
import os
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

logger = logging.getLogger("websense.db")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sentineltrace.db")
IS_SQLITE = DATABASE_URL.startswith("sqlite")

# For SQLite, enable check_same_thread=False
connect_args = {"check_same_thread": False} if IS_SQLITE else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False
)

if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")   # make ON DELETE CASCADE effective
        cur.execute("PRAGMA busy_timeout=5000")  # wait instead of 'database is locked'
        cur.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency for obtaining database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _add_missing_columns_and_indexes() -> None:
    """
    Additive, idempotent migration for databases created by older versions.

    create_all() creates missing TABLES but never alters existing ones, so any
    column or index added to a model later is added here. Only additive changes
    are made (no drops, no type changes). Failures are logged, never swallowed.
    """
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            present_cols = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in present_cols:
                    continue
                col_type = col.type.compile(dialect=engine.dialect)
                ddl = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type}'
                default = getattr(col.default, "arg", None)
                if isinstance(default, (int, float)) and not isinstance(default, bool):
                    ddl += f" DEFAULT {default}"
                elif isinstance(default, bool):
                    ddl += f" DEFAULT {1 if default else 0}" if IS_SQLITE else f" DEFAULT {str(default).upper()}"
                elif isinstance(default, str):
                    ddl += " DEFAULT '{}'".format(default.replace("'", "''"))
                try:
                    conn.execute(text(ddl))
                    logger.info("migration: added column %s.%s", table.name, col.name)
                except Exception:
                    logger.exception("migration: failed to add column %s.%s", table.name, col.name)
                    raise

            present_idx = {i["name"] for i in insp.get_indexes(table.name)}
            for idx in table.indexes:
                if idx.name in present_idx:
                    continue
                try:
                    idx.create(bind=conn, checkfirst=True)
                    logger.info("migration: created index %s", idx.name)
                except Exception:
                    logger.exception("migration: failed to create index %s", idx.name)
                    raise

        # Backfill protocol state for rows written before last_seq existed.
        if "sessions" in existing_tables:
            conn.execute(text(
                "UPDATE sessions SET last_seq = COALESCE(transmission_seq, 1) "
                "WHERE last_seq IS NULL OR last_seq = 0"
            ))
            conn.execute(text(
                "UPDATE sessions SET updated_at = created_at WHERE updated_at IS NULL"
            ))


def init_db():
    """Create all database tables and apply incremental, additive schema migrations."""
    import packages.database.models  # noqa: F401 - ensure models are registered
    Base.metadata.create_all(bind=engine)
    _add_missing_columns_and_indexes()

