from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.auth import require_admin_api_key
from app.models.source import NewsSource
from app.schemas.source import NewsSourceCreate, NewsSourceResponse, NewsSourceUpdate

router = APIRouter(prefix="/api/sources", tags=["sources"])


def _container(request: Request) -> Any:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="Source service is not configured")
    return container


@router.get("", response_model=list[NewsSourceResponse])
async def list_sources(
    request: Request,
    enabled: bool | None = None,
    category: str | None = Query(default=None, min_length=1, max_length=64),
) -> list[NewsSource]:
    statement = select(NewsSource).order_by(NewsSource.priority.desc(), NewsSource.name.asc())
    if enabled is not None:
        statement = statement.where(NewsSource.enabled.is_(enabled))
    if category is not None:
        statement = statement.where(NewsSource.category == category)
    async with _container(request).session_factory() as session:
        return list((await session.scalars(statement)).all())


@router.post("", response_model=NewsSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: NewsSourceCreate,
    request: Request,
    _: None = Depends(require_admin_api_key),
) -> NewsSource:
    source = NewsSource(**payload.model_dump())
    async with _container(request).session_factory() as session:
        session.add(source)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail="News source URL already exists") from exc
        await session.refresh(source)
        return source


@router.put("/{source_id}", response_model=NewsSourceResponse)
async def update_source(
    source_id: UUID,
    payload: NewsSourceUpdate,
    request: Request,
    _: None = Depends(require_admin_api_key),
) -> NewsSource:
    async with _container(request).session_factory() as session:
        source = cast(NewsSource | None, await session.get(NewsSource, source_id))
        if source is None:
            raise HTTPException(status_code=404, detail="News source not found")
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(source, field, value)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail="News source URL already exists") from exc
        await session.refresh(source)
        return source


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: UUID,
    request: Request,
    _: None = Depends(require_admin_api_key),
) -> Response:
    async with _container(request).session_factory() as session:
        source = await session.get(NewsSource, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="News source not found")
        await session.delete(source)
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
