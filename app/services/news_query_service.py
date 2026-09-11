"""Database-backed business operations exposed to Agent tools."""

from __future__ import annotations

from datetime import date
from typing import Any, cast
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.digest import DailyDigest
from app.models.event import NewsEvent
from app.models.news import NewsItem


class SQLAlchemyNewsToolService:
    """Repository-style service; Agent tools depend on its protocol only."""

    def __init__(self, session: AsyncSession, *, summarizer: Any = None, ranker: Any = None) -> None:
        self.session = session
        self.summarizer = summarizer
        self.ranker = ranker

    @staticmethod
    def _item_payload(item: NewsItem) -> dict[str, Any]:
        return {
            "id": str(item.id),
            "title": item.title,
            "url": item.url,
            "source_id": str(item.source_id),
            "author": item.author,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "summary": item.summary,
            "content": item.content,
            "language": item.language,
            "category": item.category,
            "tags": item.tags,
            "image_url": item.image_url,
        }

    @staticmethod
    def _event_payload(event: NewsEvent) -> dict[str, Any]:
        return {
            "id": str(event.id),
            "canonical_title": event.canonical_title,
            "summary": event.summary,
            "category": event.category,
            "importance_score": event.importance_score,
            "priority": event.priority,
            "first_seen_at": event.first_seen_at.isoformat() if event.first_seen_at else None,
            "last_seen_at": event.last_seen_at.isoformat() if event.last_seen_at else None,
            "news_items": [SQLAlchemyNewsToolService._item_payload(item) for item in event.news_items],
        }

    async def _items(self, statement: Any) -> list[dict[str, Any]]:
        items = list((await self.session.scalars(statement)).all())
        return [self._item_payload(item) for item in items]

    async def search_news(self, query: str, category: str | None, limit: int) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        statement = select(NewsItem).where(or_(NewsItem.title.ilike(pattern), NewsItem.content.ilike(pattern)))
        if category:
            statement = statement.where(NewsItem.category.ilike(category))
        statement = statement.order_by(NewsItem.published_at.desc(), NewsItem.created_at.desc()).limit(limit)
        return await self._items(statement)

    async def get_latest_news(self, category: str | None, limit: int) -> list[dict[str, Any]]:
        statement = select(NewsItem)
        if category:
            statement = statement.where(NewsItem.category.ilike(category))
        statement = statement.order_by(NewsItem.published_at.desc(), NewsItem.created_at.desc()).limit(limit)
        return await self._items(statement)

    async def get_news_by_category(self, category: str, limit: int) -> list[dict[str, Any]]:
        return await self.get_latest_news(category, limit)

    async def get_news_detail(self, news_id: UUID | None, url: str | None) -> dict[str, Any] | None:
        statement = select(NewsItem)
        if news_id is not None:
            statement = statement.where(NewsItem.id == news_id)
        elif url is not None:
            statement = statement.where(NewsItem.url == url)
        else:
            return None
        item = await self.session.scalar(statement)
        return self._item_payload(item) if item is not None else None

    async def search_events(self, query: str, category: str | None, limit: int) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        statement = (
            select(NewsEvent)
            .options(selectinload(NewsEvent.news_items))
            .where(or_(NewsEvent.canonical_title.ilike(pattern), NewsEvent.summary.ilike(pattern)))
        )
        if category:
            statement = statement.where(NewsEvent.category.ilike(category))
        statement = statement.order_by(NewsEvent.importance_score.desc(), NewsEvent.last_seen_at.desc()).limit(limit)
        events = list((await self.session.scalars(statement)).all())
        return [self._event_payload(event) for event in events]

    async def get_daily_digest(self, digest_date: date | None) -> dict[str, Any] | None:
        statement = select(DailyDigest).order_by(DailyDigest.digest_date.desc())
        if digest_date is not None:
            statement = statement.where(DailyDigest.digest_date == digest_date)
        digest = await self.session.scalar(statement)
        if digest is None:
            return None
        return {
            "id": str(digest.id),
            "digest_date": digest.digest_date.isoformat(),
            "timezone": digest.timezone,
            "status": digest.status,
            "content": digest.content,
            "sections": digest.sections,
            "generated_at": digest.generated_at.isoformat() if digest.generated_at else None,
        }

    async def _get_item_model(self, news_id: UUID) -> NewsItem | None:
        return cast(NewsItem | None, await self.session.scalar(select(NewsItem).where(NewsItem.id == news_id)))

    async def analyze_news(self, news_id: UUID, question: str | None) -> dict[str, Any]:
        item = await self._get_item_model(news_id)
        if item is None:
            return {"error": "news article not found", "news_id": str(news_id)}
        result: dict[str, Any] = {"news_id": str(news_id), "question": question, "title": item.title}
        if self.ranker is not None:
            ranking = await self.ranker.rank(item)
            result["ranking"] = ranking.model_dump(mode="json")
        else:
            result["analysis"] = "No ranking provider is configured for this tool."
        return result

    async def summarize_news(self, news_id: UUID) -> dict[str, Any]:
        item = await self._get_item_model(news_id)
        if item is None:
            return {"error": "news article not found", "news_id": str(news_id)}
        if self.summarizer is None:
            return {"news_id": str(news_id), "summary": item.summary or item.title, "source_url": item.url}
        summary = await self.summarizer.summarize(item)
        return cast(dict[str, Any], summary.model_dump(mode="json"))


__all__ = ["SQLAlchemyNewsToolService"]
