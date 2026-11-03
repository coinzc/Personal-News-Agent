"""Daily digest persistence model."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.conversation import User


class DailyDigest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One generated daily news report for a user and local calendar date."""

    __tablename__ = "daily_digests"
    __table_args__ = (
        UniqueConstraint("user_id", "digest_date", name="uq_daily_digests_user_date"),
        Index("ix_daily_digests_date_status", "digest_date", "status"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    digest_date: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", server_default="draft")
    content: Mapped[str | None] = mapped_column(Text)
    sections: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="daily_digests")

    @property
    def digest_id(self) -> UUID:
        """Return the digest primary key using the domain field name."""

        return self.id
