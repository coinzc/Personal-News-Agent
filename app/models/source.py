"""News source persistence model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.news import NewsItem


class NewsSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Configured RSS, API, or custom news source."""

    __tablename__ = "news_sources"
    __table_args__ = (
        Index("ix_news_sources_enabled_priority", "enabled", "priority"),
        Index("ix_news_sources_category", "category"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    source_type: Mapped[str] = mapped_column("type", String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    country: Mapped[str | None] = mapped_column(String(2))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    config: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    news_items: Mapped[list[NewsItem]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def source_id(self) -> UUID:
        """Return the source primary key using the domain field name."""

        return self.id

    @property
    def type(self) -> str:
        """Return the configured collector type (RSS, API, or custom)."""

        return self.source_type

    @type.setter
    def type(self, value: str) -> None:
        self.source_type = value
