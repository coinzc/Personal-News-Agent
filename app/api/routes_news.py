from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from app.services.news_query_service import SQLAlchemyNewsToolService

router = APIRouter(prefix="/api/news", tags=["news"])


def _session_factory(request: Request) -> Any:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="News service is not configured")
    return container.session_factory


@router.get("")
async def list_news(
    request: Request,
    q: str | None = Query(default=None, min_length=1, max_length=200),
    category: str | None = Query(default=None, min_length=1, max_length=64),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, object]]:
    async with _session_factory(request)() as session:
        service = SQLAlchemyNewsToolService(session)
        if q:
            return await service.search_news(q, category, limit)
        return await service.get_latest_news(category, limit)


@router.get("/{news_id}")
async def get_news(news_id: UUID, request: Request) -> dict[str, object]:
    async with _session_factory(request)() as session:
        result = await SQLAlchemyNewsToolService(session).get_news_detail(news_id, None)
    if result is None:
        raise HTTPException(status_code=404, detail="News article not found")
    return result
