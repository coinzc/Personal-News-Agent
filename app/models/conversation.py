"""Users and Agent conversation persistence models."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.digest import DailyDigest


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person allowed to use the news agent."""

    __tablename__ = "users"
    __table_args__ = (Index("ix_users_active", "is_active"),)

    wechat_openid: Mapped[str | None] = mapped_column(String(128), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Singapore")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    daily_digests: Mapped[list[DailyDigest]] = relationship(back_populates="user")
    conversations: Mapped[list[AgentConversation]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def user_id(self) -> UUID:
        """Return the user primary key using the domain field name."""

        return self.id


class AgentConversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A channel-specific conversation session with the Agent."""

    __tablename__ = "agent_conversations"
    __table_args__ = (
        UniqueConstraint("session_key", name="uq_agent_conversations_session_key"),
        Index("ix_agent_conversations_user_updated_at", "user_id", "updated_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_key: Mapped[str] = mapped_column(String(255), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="wechat")
    title: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list[AgentMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AgentMessage.created_at",
    )

    @property
    def conversation_id(self) -> UUID:
        """Return the conversation primary key using the domain field name."""

        return self.id


class AgentMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One user, assistant, system, or tool message in a conversation."""

    __tablename__ = "agent_messages"
    __table_args__ = (Index("ix_agent_messages_conversation_created_at", "conversation_id", "created_at"),)

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(128))
    tool_call_id: Mapped[str | None] = mapped_column(String(128))
    message_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )

    conversation: Mapped[AgentConversation] = relationship(back_populates="messages")

    @property
    def message_id(self) -> UUID:
        """Return the message primary key using the domain field name."""

        return self.id
