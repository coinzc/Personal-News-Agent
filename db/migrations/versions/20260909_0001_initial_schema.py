"""Create the initial Phase 2 database schema.

Revision ID: 20260909_0001
Revises:
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260909_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def upgrade() -> None:
    """Create the initial schema using explicit, reviewable operations."""

    uuid = sa.Uuid(as_uuid=True)
    op.create_table(
        "users",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("wechat_openid", sa.String(128), unique=True),
        sa.Column("display_name", sa.String(255)),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
    )
    op.create_index("ix_users_active", "users", ["is_active"])

    op.create_table(
        "news_sources",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, unique=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("country", sa.String(2)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("last_collected_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_news_sources_enabled_priority", "news_sources", ["enabled", "priority"])
    op.create_index("ix_news_sources_category", "news_sources", ["category"])

    op.create_table(
        "news_categories",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
    )
    op.create_index("ix_news_categories_enabled_sort_order", "news_categories", ["enabled", "sort_order"])

    op.create_table(
        "news_items",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("source_id", uuid, sa.ForeignKey("news_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, unique=True),
        sa.Column("author", sa.String(255)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("content", sa.Text()),
        sa.Column("summary", sa.Text()),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("image_url", sa.Text()),
        sa.Column("hash", sa.String(64), unique=True),
        *_timestamps(),
    )
    op.create_index("ix_news_items_source_id", "news_items", ["source_id"])
    op.create_index("ix_news_items_published_at", "news_items", ["published_at"])
    op.create_index("ix_news_items_category", "news_items", ["category"])
    op.create_index("ix_news_items_source_published_at", "news_items", ["source_id", "published_at"])
    op.create_index("ix_news_items_category_published_at", "news_items", ["category", "published_at"])

    op.create_table(
        "news_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("canonical_title", sa.String(500), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("importance_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("priority", sa.String(16), nullable=False, server_default="low"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_news_events_category_importance", "news_events", ["category", "importance_score"])
    op.create_index("ix_news_events_last_seen_at", "news_events", ["last_seen_at"])

    op.create_table(
        "event_news",
        sa.Column("event_id", uuid, sa.ForeignKey("news_events.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("news_item_id", uuid, sa.ForeignKey("news_items.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_timestamps(),
    )

    op.create_table(
        "daily_digests",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("user_id", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("digest_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("content", sa.Text()),
        sa.Column("sections", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("generated_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        *_timestamps(),
        sa.UniqueConstraint("user_id", "digest_date", name="uq_daily_digests_user_date"),
    )
    op.create_index("ix_daily_digests_date_status", "daily_digests", ["digest_date", "status"])

    op.create_table(
        "agent_conversations",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("user_id", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_key", sa.String(255), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.UniqueConstraint("session_key", name="uq_agent_conversations_session_key"),
    )
    op.create_index("ix_agent_conversations_user_updated_at", "agent_conversations", ["user_id", "updated_at"])

    op.create_table(
        "agent_messages",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "conversation_id",
            uuid,
            sa.ForeignKey("agent_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.String(128)),
        sa.Column("tool_call_id", sa.String(128)),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        *_timestamps(),
    )
    op.create_index("ix_agent_messages_conversation_created_at", "agent_messages", ["conversation_id", "created_at"])

    op.create_table(
        "tasks",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("result", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error_message", sa.Text()),
        *_timestamps(),
    )
    op.create_index("ix_tasks_status_scheduled_for", "tasks", ["status", "scheduled_for"])
    op.create_index("ix_tasks_task_type_created_at", "tasks", ["task_type", "created_at"])


def downgrade() -> None:
    """Drop the initial schema in reverse dependency order."""

    op.drop_index("ix_tasks_task_type_created_at", table_name="tasks")
    op.drop_index("ix_tasks_status_scheduled_for", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_agent_messages_conversation_created_at", table_name="agent_messages")
    op.drop_table("agent_messages")
    op.drop_index("ix_agent_conversations_user_updated_at", table_name="agent_conversations")
    op.drop_table("agent_conversations")
    op.drop_index("ix_daily_digests_date_status", table_name="daily_digests")
    op.drop_table("daily_digests")
    op.drop_table("event_news")
    op.drop_index("ix_news_events_last_seen_at", table_name="news_events")
    op.drop_index("ix_news_events_category_importance", table_name="news_events")
    op.drop_table("news_events")
    op.drop_index("ix_news_items_category_published_at", table_name="news_items")
    op.drop_index("ix_news_items_source_published_at", table_name="news_items")
    op.drop_index("ix_news_items_category", table_name="news_items")
    op.drop_index("ix_news_items_published_at", table_name="news_items")
    op.drop_index("ix_news_items_source_id", table_name="news_items")
    op.drop_table("news_items")
    op.drop_index("ix_news_categories_enabled_sort_order", table_name="news_categories")
    op.drop_table("news_categories")
    op.drop_index("ix_news_sources_category", table_name="news_sources")
    op.drop_index("ix_news_sources_enabled_priority", table_name="news_sources")
    op.drop_table("news_sources")
    op.drop_index("ix_users_active", table_name="users")
    op.drop_table("users")
