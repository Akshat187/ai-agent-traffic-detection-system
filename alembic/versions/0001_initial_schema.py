"""Initial SentinelTrace schema baseline

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure all tables and additive columns exist cleanly across SQLite & PostgreSQL
    from packages.database.db import init_db
    init_db()


def downgrade() -> None:
    pass
