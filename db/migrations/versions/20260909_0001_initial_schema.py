"""Create the initial Phase 2 database schema.

Revision ID: 20260909_0001
Revises:
Create Date: 2026-09-09
"""

from collections.abc import Sequence

from alembic import op
from app.db.base import Base
from app.models import category, conversation, digest, event, news, source, task  # noqa: F401

revision: str = "20260909_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all initial ORM tables and indexes."""

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """Drop all tables created by this initial revision."""

    Base.metadata.drop_all(bind=op.get_bind())
