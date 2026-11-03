"""Persisted DailyDigest delivery through an injected message channel."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.base import MessageChannel
from app.models.digest import DailyDigest

logger = logging.getLogger(__name__)


class DigestDeliveryService:
    def __init__(self, session: AsyncSession, channel: MessageChannel) -> None:
        self.session = session
        self.channel = channel

    @staticmethod
    def compact_content(digest: DailyDigest) -> str:
        """Build a phone-friendly delivery view without changing persisted content."""

        payload = digest.sections or {}
        categories = payload.get("categories", {})
        if not isinstance(categories, dict):
            categories = {}
        active = [(str(category), rows) for category, rows in categories.items() if isinstance(rows, list) and rows]
        all_rows = [row for _, rows in active for row in rows if isinstance(row, dict)]
        separator = "━━━━━━━━━━━━━━"
        lines = [
            "今日新闻早报",
            f"{digest.digest_date.isoformat()} 09:00（北京时间）",
            "",
            separator,
            "今日头条",
            separator,
        ]
        if all_rows:
            lines.extend(DigestDeliveryService._format_compact_rows(all_rows[:3]))
        else:
            lines.append("暂无可用新闻")
        links: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for category, rows in active:
            lines.extend(["", separator, category, separator])
            lines.extend(DigestDeliveryService._format_compact_rows(rows[:3]))
            for row in rows[:3]:
                if isinstance(row, dict) and row.get("url") and row["url"] not in seen_urls:
                    seen_urls.add(str(row["url"]))
                    links.append(row)
        lines.extend(["", separator, "今日趋势", separator, str(payload.get("trend_analysis") or "暂无趋势分析")])
        lines.extend(["", separator, "今日最值得关注的 3 件事", separator])
        top_titles = [f"{index}. {row.get('title', '未命名新闻')}" for index, row in enumerate(all_rows[:3], 1)]
        lines.extend(top_titles or ["暂无可用新闻"])
        if links:
            lines.extend(["", separator, "原文链接", separator])
            for index, row in enumerate(links, 1):
                lines.extend([f"{index}. {row.get('title', '未命名新闻')}", f"   {row['url']}"])
        return "\n".join(lines)

    @staticmethod
    def _format_compact_rows(rows: Iterable[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        for index, row in enumerate(rows, 1):
            lines.extend(
                [
                    f"{index}. {row.get('title', '未命名新闻')}",
                    f"   {row.get('summary', '暂无摘要')}",
                    f"   时间：{row.get('published_at', '时间未知')}｜来源：{row.get('source_name', '未知来源')}",
                ]
            )
        return lines

    async def send_daily_digest(self, digest: DailyDigest, recipient: str) -> bool:
        if digest.status not in {"completed", "sent"} or not digest.content:
            return False
        try:
            await self.channel.send_text(recipient, self.compact_content(digest))
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
