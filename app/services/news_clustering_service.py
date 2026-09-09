"""Persistence service for grouping articles into ``NewsEvent`` records."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.event import EventNews, NewsEvent
from app.models.news import NewsItem
from app.services.news_dedup_service import DeduplicationMatch, NewsDedupService, TitleMatch

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _EventContext:
    event: NewsEvent
    items: list[NewsItem]


class NewsClusteringService:
    """Create/reuse events and retain every article/source as an association.

    The service intentionally works with the existing Phase 2 association
    object.  It does not delete duplicate ``NewsItem`` rows and is idempotent
    when called again for already-linked items.
    """

    def __init__(self, session: AsyncSession, dedup_service: NewsDedupService | None = None) -> None:
        self.session = session
        self.dedup_service = dedup_service or NewsDedupService()

    async def cluster_items(self, items: Sequence[NewsItem], *, commit: bool = True) -> list[NewsEvent]:
        """Assign supplied persisted items to existing or newly-created events.

        Existing events are loaded with their association rows in one eager
        loading pass.  The batch is processed deterministically in its input
        order; the best matching event is selected for each new item.
        """

        if not items:
            return []

        # Collector ingestion normally flushes items before this service runs.
        # Flushing here also supports callers that add a batch and immediately
        # invoke clustering in the same transaction.
        for item in items:
            # `Session` keeps an identity map; checking `new` avoids
            # re-adding objects that are already persistent in this session.
            if item not in self.session.new and item not in self.session.identity_map.values():
                self.session.add(item)
        await self.session.flush()

        contexts = await self._load_event_contexts()
        event_by_item_id: dict[UUID, _EventContext] = {}
        for context in contexts:
            for linked_item in context.items:
                event_by_item_id[linked_item.id] = context

        touched: list[NewsEvent] = []
        touched_ids: set[UUID] = set()
        try:
            for item in items:
                existing_context = event_by_item_id.get(item.id)
                if existing_context is not None:
                    self._update_event_window(existing_context.event, item)
                    self._record_touched(existing_context.event, touched, touched_ids)
                    continue

                selected_context, evidence = await self._best_event_match(item, contexts)
                if selected_context is None:
                    event = NewsEvent(
                        canonical_title=item.title,
                        category=item.category,
                        first_seen_at=self._item_timestamp(item),
                        last_seen_at=self._item_timestamp(item),
                        event_news=[],
                    )
                    self.session.add(event)
                    await self.session.flush()
                    selected_context = _EventContext(event=event, items=[])
                    contexts.append(selected_context)
                    logger.info("Created news event %s for %s", event.id, item.url)
                elif evidence is not None:
                    logger.debug(
                        "Matched %s to event %s via %s (%.3f)",
                        item.url,
                        selected_context.event.id,
                        evidence.stage,
                        evidence.score,
                    )

                self._attach_item(selected_context.event, item)
                selected_context.items.append(item)
                event_by_item_id[item.id] = selected_context
                self._update_event_window(selected_context.event, item)
                self._record_touched(selected_context.event, touched, touched_ids)

            await self.session.flush()
            if commit:
                await self.session.commit()
        except Exception:
            if commit:
                await self.session.rollback()
            raise

        logger.info("Clustered %d news items into %d events", len(items), len(touched))
        return touched

    async def cluster_pending(self, *, limit: int | None = None, commit: bool = True) -> list[NewsEvent]:
        """Cluster every article that has no ``event_news`` association yet."""

        stmt = (
            select(NewsItem)
            .outerjoin(EventNews, EventNews.news_item_id == NewsItem.id)
            .where(EventNews.news_item_id.is_(None))
            .order_by(NewsItem.published_at.asc(), NewsItem.created_at.asc())
        )
        if limit is not None:
            if limit <= 0:
                raise ValueError("limit must be greater than zero")
            stmt = stmt.limit(limit)
        pending = list((await self.session.scalars(stmt)).all())
        return await self.cluster_items(pending, commit=commit)

    async def cluster(self, items: Sequence[NewsItem], *, commit: bool = True) -> list[NewsEvent]:
        """Backward-compatible concise alias for :meth:`cluster_items`."""

        return await self.cluster_items(items, commit=commit)

    async def _load_event_contexts(self) -> list[_EventContext]:
        stmt = select(NewsEvent).options(selectinload(NewsEvent.event_news).selectinload(EventNews.news_item))
        events = list((await self.session.scalars(stmt)).all())
        return [
            _EventContext(
                event=event, items=[link.news_item for link in event.event_news if link.news_item is not None]
            )
            for event in events
        ]

    async def _best_event_match(
        self,
        item: NewsItem,
        contexts: Sequence[_EventContext],
    ) -> tuple[_EventContext | None, TitleMatch | DeduplicationMatch | None]:
        best_context: _EventContext | None = None
        best_match: TitleMatch | DeduplicationMatch | None = None
        for context in contexts:
            # Compare against all linked headlines so a later, more precise
            # headline can still join an event whose canonical title was brief.
            candidates = context.items
            duplicate = await self.dedup_service.find_duplicate(item, candidates) if candidates else None
            canonical = await self.dedup_service.compare_titles(item.title, context.event.canonical_title)
            candidate_match: TitleMatch | DeduplicationMatch | None = duplicate
            if canonical is not None and (candidate_match is None or canonical.score > candidate_match.score):
                candidate_match = canonical
            if candidate_match is None:
                continue
            if best_match is None or candidate_match.score > best_match.score:
                best_context, best_match = context, candidate_match
        return best_context, best_match

    @staticmethod
    def _attach_item(event: NewsEvent, item: NewsItem) -> None:
        if any(link.news_item_id == item.id for link in event.event_news):
            return
        event.event_news.append(EventNews(news_item=item, is_primary=not bool(event.event_news)))

    @staticmethod
    def _item_timestamp(item: NewsItem) -> datetime:
        timestamp = item.published_at or item.created_at
        return timestamp or datetime.now(UTC)

    @classmethod
    def _update_event_window(cls, event: NewsEvent, item: NewsItem) -> None:
        timestamp = cls._item_timestamp(item)
        if event.first_seen_at is None or timestamp < event.first_seen_at:
            event.first_seen_at = timestamp
        if event.last_seen_at is None or timestamp > event.last_seen_at:
            event.last_seen_at = timestamp

    @staticmethod
    def _record_touched(event: NewsEvent, touched: list[NewsEvent], touched_ids: set[UUID]) -> None:
        event_id = event.id
        if event_id not in touched_ids:
            touched.append(event)
            touched_ids.add(event_id)


__all__ = ["NewsClusteringService"]
