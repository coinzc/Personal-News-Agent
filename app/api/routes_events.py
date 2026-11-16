from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.services.news_query_service import SQLAlchemyNewsToolService

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("")
async def list_events(
    request: Request,
    q: str = Query(default="", max_length=200),
    category: str | None = Query(default=None, min_length=1, max_length=64),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, object]]:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="Event service is not configured")
    async with container.session_factory() as session:
        return await SQLAlchemyNewsToolService(session).search_events(q, category, limit)
