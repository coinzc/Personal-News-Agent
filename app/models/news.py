"""News item persistence model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.event import EventNews, NewsEvent
    from app.models.source import NewsSource


class NewsItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A normalized article collected from one configured news source."""

    __tablename__ = "news_items"
    __table_args__ = (
        UniqueConstraint("url", name="uq_news_items_url"),
        UniqueConstraint("hash", name="uq_news_items_hash"),
        Index("ix_news_items_source_published_at", "source_id", "published_at"),
        Index("ix_news_items_category_published_at", "category", "published_at"),
    )

    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("news_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    author: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    content: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    image_url: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column("hash", String(64))

    source: Mapped[NewsSource] = relationship(back_populates="news_items")
    event_links: Mapped[list[EventNews]] = relationship(
        back_populates="news_item",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    events: Mapped[list[NewsEvent]] = relationship(
        secondary="event_news",
        back_populates="news_items",
        viewonly=True,
        overlaps="event_links,event,news_item",
    )

    @property
    def news_item_id(self) -> UUID:
        """Return the item primary key using the domain field name."""

        return self.id

    @property
    def hash(self) -> str | None:
        """Return the content hash using the persisted field name."""

        return self.content_hash

    @hash.setter
    def hash(self, value: str | None) -> None:
        self.content_hash = value
