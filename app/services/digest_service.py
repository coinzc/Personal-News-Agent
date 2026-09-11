"""Daily news digest orchestration and persistence.

The service coordinates the daily pipeline without coupling it to a concrete
collector, LLM provider, or delivery channel.  All external steps are
injectable, which keeps the unit tests deterministic and lets the scheduler
reuse the same application service in production.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.digest import DailyDigest
from app.models.news import NewsItem
from app.models.task import Task

logger = logging.getLogger(__name__)

DEFAULT_CATEGORIES: tuple[str, ...] = ("AI", "科技", "编程", "财经", "商业", "国际", "科学", "游戏")


class DigestLock(Protocol):
    async def __aenter__(self) -> DigestLock: ...

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None: ...


class RedisDigestLock:
    """Non-blocking Redis lock; a second worker simply skips the run."""

    def __init__(self, redis: Any, key: str, *, timeout: int = 1_800) -> None:
        self._lock = redis.lock(key, timeout=timeout, blocking=False)

    async def __aenter__(self) -> RedisDigestLock:
        acquired = await self._lock.acquire(blocking=False)
        if not acquired:
            raise DigestAlreadyRunning("daily digest is already running")
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        try:
            await self._lock.release()
        except Exception:  # pragma: no cover - defensive cleanup
            logger.exception("Failed to release daily digest Redis lock")


class DigestAlreadyRunning(RuntimeError):
    """Another worker currently owns the digest lock."""


class DigestGenerationError(RuntimeError):
    """The digest pipeline failed and was recorded as a failed task."""


NewsStep = Callable[[Sequence[NewsItem]], Awaitable[Sequence[NewsItem]]]
SummaryStep = Callable[[NewsItem], Awaitable[dict[str, Any]]]
TrendStep = Callable[[dict[str, list[dict[str, Any]]]], Awaitable[str]]


class DailyDigestService:
    """Generate one idempotent, source-grounded digest per local calendar day."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        redis: Any | None = None,
        user_id: UUID | None = None,
        timezone: str | None = None,
        categories: Sequence[str] = DEFAULT_CATEGORIES,
        deduplicate: NewsStep | None = None,
        cluster: NewsStep | None = None,
        rank: NewsStep | None = None,
        summarize: SummaryStep | None = None,
        trend: TrendStep | None = None,
        lock_factory: Callable[[str], DigestLock] | None = None,
        max_chars: int = 12_000,
    ) -> None:
        self.session = session
        self.redis = redis
        self.user_id = user_id
        self.timezone = timezone or get_settings().timezone
        self.categories = tuple(categories)
        self.deduplicate = deduplicate
        self.cluster = cluster
        self.rank = rank
        self.summarize = summarize
        self.trend = trend
        self.lock_factory = lock_factory
        self.max_chars = max_chars

    def _lock(self, digest_date: date) -> DigestLock:
        key = f"news-agent:digest:{self.user_id or 'global'}:{digest_date.isoformat()}"
        if self.lock_factory is not None:
            return self.lock_factory(key)
        if self.redis is not None:
            return RedisDigestLock(self.redis, key)
        return _NoopDigestLock()

    def local_today(self) -> date:
        return datetime.now(ZoneInfo(self.timezone)).date()

    async def generate_daily_digest(self, digest_date: date | None = None) -> DailyDigest:
        """Run Collect -> Deduplicate -> Cluster -> Rank -> Summarize -> Compose.

        A unique database constraint is the final idempotency guard in addition
        to the Redis lock.  Existing completed digests are returned unchanged.
        """

        target_date = digest_date or self.local_today()
        async with self._lock(target_date):
            existing = await self._existing_digest(target_date)
            if existing is not None and existing.status == "completed":
                return existing
            task = Task(
                task_type="generate_daily_digest",
                status="running",
                attempts=1,
                scheduled_for=datetime.combine(target_date, datetime.min.time(), tzinfo=ZoneInfo(self.timezone)),
                started_at=datetime.now(UTC),
                payload={"digest_date": target_date.isoformat(), "timezone": self.timezone},
            )
            self.session.add(task)
            digest = existing or DailyDigest(
                user_id=self.user_id or UUID(int=0),
                digest_date=target_date,
                timezone=self.timezone,
                status="running",
                sections={},
            )
            if existing is None:
                self.session.add(digest)
            else:
                digest.status = "running"
                digest.error_message = None
            await self.session.flush()
            try:
                items = await self._load_items(target_date)
                sections = await self._build_sections(items)
                trend = await self.trend(sections) if self.trend is not None else self._default_trend(sections)
                content = self._compose(target_date, sections, trend)
                digest.sections = {"categories": sections, "trend_analysis": trend}
                digest.content = content[: self.max_chars]
                digest.status = "completed"
                digest.generated_at = datetime.now(UTC)
                task.status = "completed"
                task.finished_at = datetime.now(UTC)
                task.result = {"digest_id": str(digest.id), "categories": len(sections)}
                await self.session.commit()
                logger.info("Daily digest generated date=%s categories=%d", target_date, len(sections))
                return digest
            except Exception as exc:
                digest.status = "failed"
                digest.error_message = str(exc)[:2_000]
                task.status = "failed"
                task.finished_at = datetime.now(UTC)
                task.error_message = str(exc)[:2_000]
                await self.session.commit()
                logger.exception("Daily digest generation failed date=%s", target_date)
                raise DigestGenerationError(f"daily digest generation failed for {target_date}") from exc

    async def _existing_digest(self, target_date: date) -> DailyDigest | None:
        stmt = select(DailyDigest).where(DailyDigest.digest_date == target_date)
        if self.user_id is not None:
            stmt = stmt.where(DailyDigest.user_id == self.user_id)
        return await self.session.scalar(stmt)

    async def _load_items(self, target_date: date) -> list[NewsItem]:
        start_local = datetime.combine(target_date, datetime.min.time(), tzinfo=ZoneInfo(self.timezone))
        end_local = start_local + timedelta(days=1)
        stmt = (
            select(NewsItem)
            .options(selectinload(NewsItem.events))
            .where(
                NewsItem.published_at >= start_local.astimezone(UTC), NewsItem.published_at < end_local.astimezone(UTC)
            )
        )
        return list((await self.session.scalars(stmt.order_by(NewsItem.published_at.desc()))).all())

    async def _build_sections(self, items: Sequence[NewsItem]) -> dict[str, list[dict[str, Any]]]:
        current: Sequence[NewsItem] = items
        for step in (self.deduplicate, self.cluster, self.rank):
            if step is not None:
                current = await step(current)
        sections: dict[str, list[dict[str, Any]]] = {}
        for category in self.categories:
            candidates = [item for item in current if item.category.casefold() == category.casefold()]
            candidates.sort(key=lambda item: getattr(item, "importance_score", 0.0) or 0.0, reverse=True)
            rows: list[dict[str, Any]] = []
            seen_events: set[UUID] = set()
            for item in candidates:
                event_id = next((event.id for event in getattr(item, "events", []) if event is not None), None)
                if event_id is not None and event_id in seen_events:
                    continue
                if event_id is not None:
                    seen_events.add(event_id)
                summary = (item.summary or item.title).strip()
                if self.summarize is not None:
                    result = await self.summarize(item)
                    summary = str(result.get("summary") or summary)
                rows.append(
                    {
                        "title": item.title,
                        "summary": summary,
                        "why_important": self._why_important(item),
                        "url": item.url,
                        "published_at": item.published_at.isoformat() if item.published_at else None,
                        "source_id": str(item.source_id),
                    }
                )
                if len(rows) == 3:
                    break
            sections[category] = rows
        return sections

    @staticmethod
    def _why_important(item: NewsItem) -> str:
        score = getattr(item, "importance_score", None)
        if score is not None:
            return f"重要性评分 {float(score):.1f}/100，可能影响 {item.category} 领域。"
        return f"该消息与 {item.category} 领域直接相关，值得持续关注。"

    @staticmethod
    def _default_trend(sections: dict[str, list[dict[str, Any]]]) -> str:
        active = [category for category, rows in sections.items() if rows]
        return "今日覆盖领域：" + ("、".join(active) if active else "暂无新闻数据") + "。"

    @staticmethod
    def _format_row(row: dict[str, Any]) -> str:
        headline = f"- {row['title']}：{row['summary']}（为什么重要：{row['why_important']}）"
        provenance = f"来源：{row['url']} | 时间：{row['published_at'] or '未知'}"
        return f"{headline}`n  {provenance}"

    def _compose(self, target_date: date, sections: dict[str, list[dict[str, Any]]], trend: str) -> str:
        lines = ["# 今日新闻早报", f"日期：{target_date.isoformat()}", ""]
        all_rows = [row for rows in sections.values() for row in rows]
        lines.extend(
            [
                "## 今日头条",
                *[self._format_row(row) for row in all_rows[:3]],
                "",
            ]
        )
        for category in self.categories:
            lines.append(f"## {category}")
            rows = sections.get(category, [])
            lines.extend([self._format_row(row) for row in rows] or ["- 今日暂无可用新闻。"])
            lines.append("")
        lines.extend(["## 今日趋势", trend, "", "## 今日最值得关注的 3 件事"])
        lines.extend([f"{index}. {row['title']}" for index, row in enumerate(all_rows[:3], 1)] or ["暂无新闻。"])
        return "\n".join(lines)


class _NoopDigestLock:
    async def __aenter__(self) -> _NoopDigestLock:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


__all__ = [
    "DEFAULT_CATEGORIES",
    "DailyDigestService",
    "DigestAlreadyRunning",
    "DigestGenerationError",
    "RedisDigestLock",
]
