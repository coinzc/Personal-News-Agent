"""News category persistence model."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class NewsCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Configurable top-level or subcategory used by news classification."""

    __tablename__ = "news_categories"
    __table_args__ = (Index("ix_news_categories_enabled_sort_order", "enabled", "sort_order"),)

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    @property
    def category_id(self) -> UUID:
        """Return the category primary key using the domain field name."""

        return self.id
