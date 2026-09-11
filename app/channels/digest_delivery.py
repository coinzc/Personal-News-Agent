"""Persisted DailyDigest delivery through an injected message channel."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.base import MessageChannel
from app.models.digest import DailyDigest

logger = logging.getLogger(__name__)


class DigestDeliveryService:
    def __init__(self, session: AsyncSession, channel: MessageChannel) -> None:
        self.session = session
        self.channel = channel

    async def send_daily_digest(self, digest: DailyDigest, recipient: str) -> bool:
        if digest.status not in {"completed", "sent"} or not digest.content:
            return False
        try:
            await self.channel.send_text(recipient, digest.content)
            digest.status = "sent"
            digest.sent_at = datetime.now(UTC)
            digest.error_message = None
            await self.session.commit()
            logger.info("Daily digest sent digest_id=%s recipient=%s", digest.id, recipient)
            return True
        except Exception as exc:
            digest.status = "send_failed"
            digest.error_message = str(exc)[:2_000]
            await self.session.commit()
            logger.exception("Daily digest delivery failed digest_id=%s", digest.id)
            return False


__all__ = ["DigestDeliveryService"]
