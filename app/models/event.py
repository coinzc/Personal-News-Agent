"""News event and event-to-news association models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.news import NewsItem


class NewsEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Clustered real-world event supported by one or more news items."""

    __tablename__ = "news_events"
    __table_args__ = (
        Index("ix_news_events_category_importance", "category", "importance_score"),
        Index("ix_news_events_last_seen_at", "last_seen_at"),
    )

    canonical_title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    importance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="low", server_default="low")
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    event_news: Mapped[list[EventNews]] = relationship(
        back_populates="event", cascade="all, delete-orphan", passive_deletes=True
    )
    news_items: Mapped[list[NewsItem]] = relationship(
        secondary="event_news",
        back_populates="events",
        viewonly=True,
        overlaps="event_news,event,news_item,event_links",
    )

    @property
    def event_id(self) -> UUID:
        """Return the event primary key using the domain field name."""

        return self.id


class EventNews(TimestampMixin, Base):
    """Association object linking a news item to a clustered event."""

    __tablename__ = "event_news"

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("news_events.id", ondelete="CASCADE"), primary_key=True
    )
    news_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("news_items.id", ondelete="CASCADE"), primary_key=True
    )
    is_primary: Mapped[bool] = mapped_column(default=False, server_default="false", nullable=False)

    event: Mapped[NewsEvent] = relationship(back_populates="event_news")
    news_item: Mapped[NewsItem] = relationship(back_populates="event_links")
