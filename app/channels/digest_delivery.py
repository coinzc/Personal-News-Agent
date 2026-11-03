"""Persisted DailyDigest delivery through an injected message channel."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.base import MessageChannel
from app.models.digest import DailyDigest

logger = logging.getLogger(__name__)

_CATEGORY_ORDER = ("AI", "科技", "编程", "财经", "商业", "国际", "科学")
_CATEGORY_EMOJIS = {
    "AI": "🤖",
    "科技": "💻",
    "编程": "👨‍💻",
    "财经": "📈",
    "商业": "💼",
    "国际": "🌍",
    "科学": "🔬",
}


def _clean_display_text(value: object, *, fallback: str) -> str:
    """Remove provider-added interaction metadata from user-facing text."""

    text = str(value or fallback).strip()
    text = re.sub(r"https?://\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:点赞数|点赞|likes?)\s*[:：]?\s*\d+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:评论数|评论|comments?)\s*[:：]?\s*\d+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:点数|得分|获得|得到)\s*[:：]?\s*\d+\s*分?", "", text)
    text = re.sub(r"(?:共有|共)\s*\d+\s*条?评论", "", text)
    text = re.sub(r"评论链接?", "", text)
    text = re.sub(r"\s*[|｜]\s*", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return re.sub(r"^[\s|｜,，;；-]+|[\s|｜,，;；-]+$", "", text) or fallback


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
        available = {
            str(category): rows
            for category, rows in categories.items()
            if str(category) in _CATEGORY_ORDER and isinstance(rows, list) and rows
        }
        active = [(category, available[category]) for category in _CATEGORY_ORDER if category in available]
        all_rows = [row for _, rows in active for row in rows if isinstance(row, dict)]
        separator = "━━━━━━━━━━━━━━"
        lines = [
            "今日新闻早报",
            f"{digest.digest_date.isoformat()} 09:00（北京时间）",
            "",
        ]
        links: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for category, rows in active:
            lines.extend(["", separator, f"{_CATEGORY_EMOJIS[category]} {category}", separator])
            lines.extend(DigestDeliveryService._format_compact_rows(rows[:3]))
            for row in rows[:3]:
                if isinstance(row, dict) and row.get("url") and row["url"] not in seen_urls:
                    seen_urls.add(str(row["url"]))
                    links.append(row)
        if not all_rows:
            lines.extend(["", separator, "暂无可用新闻", separator])
        raw_trend = str(payload.get("trend_analysis") or "")
        if raw_trend.startswith("今日覆盖领域："):
            trend = "今日覆盖领域：" + ("、".join(category for category, _ in active) or "暂无新闻数据") + "。"
        else:
            trend = _clean_display_text(raw_trend, fallback="暂无趋势分析")
        lines.extend(["", separator, "今日趋势", separator, trend])
        lines.extend(["", separator, "今日最值得关注的 3 件事", separator])
        top_titles = [
            f"{index}. {_clean_display_text(row.get('title'), fallback='未命名新闻')}"
            for index, row in enumerate(all_rows[:3], 1)
        ]
        lines.extend(top_titles or ["暂无可用新闻"])
        if links:
            lines.extend(["", separator, "原文链接", separator])
            for index, row in enumerate(links, 1):
                lines.extend(
                    [
                        f"{index}. {_clean_display_text(row.get('title'), fallback='未命名新闻')}",
                        f"   {row['url']}",
                    ]
                )
        return "\n".join(lines)

    @staticmethod
    def _format_compact_rows(rows: Iterable[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        for index, row in enumerate(rows, 1):
            lines.extend(
                [
                    f"{index}. {_clean_display_text(row.get('title'), fallback='未命名新闻')}",
                    f"   {_clean_display_text(row.get('summary'), fallback='暂无摘要')}",
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
