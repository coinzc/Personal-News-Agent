from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import pytest
from app.config import Settings
from app.db.base import Base
from app.main import create_app
from app.models import DailyDigest, EventNews, NewsEvent, NewsItem, NewsSource, User
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_news_event_digest_and_source_routes(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'resources.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app = create_app(Settings(app_env="testing", admin_api_key="admin-secret"))
    app.state.settings = Settings(app_env="testing", admin_api_key="admin-secret")
    app.state.container = SimpleNamespace(session_factory=factory, settings=app.state.settings)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        source_payload = {
            "name": "Test RSS",
            "url": "https://example.test/rss",
            "source_type": "rss",
            "category": "AI",
            "config": {"api_token": "must-not-be-returned"},
        }
        created = await client.post("/api/sources", headers={"X-API-Key": "admin-secret"}, json=source_payload)
        assert created.status_code == 201
        source_id = created.json()["id"]
        assert "config" not in created.json()

        async with factory() as session:
            source = await session.get(NewsSource, UUID(source_id))
            assert source is not None
            user = User(display_name="API user")
            item = NewsItem(
                source_id=source.id,
                title="OpenAI releases a new model",
                url="https://example.test/article",
                category="AI",
                language="en",
                published_at=datetime.now(UTC),
            )
            event = NewsEvent(canonical_title="OpenAI releases a new model", category="AI", importance_score=88)
            session.add_all([user, item, event])
            await session.flush()
            session.add(EventNews(event=event, news_item=item, is_primary=True))
            session.add(
                DailyDigest(
                    user_id=user.id,
                    digest_date=datetime.now(ZoneInfo("Asia/Shanghai")).date(),
                    timezone="Asia/Shanghai",
                    status="completed",
                    content="Today's digest",
                    sections={"categories": {}, "trend_analysis": ""},
                )
            )
            await session.commit()

        duplicate = await client.post("/api/sources", headers={"X-API-Key": "admin-secret"}, json=source_payload)
        assert duplicate.status_code == 409

        listed = await client.get("/api/sources")
        assert listed.status_code == 200
        assert listed.json()[0]["name"] == "Test RSS"
        assert "config" not in listed.json()[0]

        updated = await client.put(
            f"/api/sources/{source_id}",
            headers={"X-API-Key": "admin-secret"},
            json={"enabled": False, "priority": 10},
        )
        assert updated.status_code == 200
        assert updated.json()["enabled"] is False
        assert updated.json()["priority"] == 10

        news_response = await client.get("/api/news", params={"q": "OpenAI"})
        assert news_response.status_code == 200
        assert news_response.json()[0]["title"] == "OpenAI releases a new model"
        assert news_response.json()[0]["source_name"] == "Test RSS"
        assert news_response.json()[0]["importance_score"] == 88
        events_response = await client.get("/api/events", params={"q": "OpenAI"})
        assert events_response.status_code == 200
        assert events_response.json()[0]["importance_score"] == 88
        digest_response = await client.get("/api/digest/today")
        assert digest_response.status_code == 200
        assert digest_response.json()["content"] == "Today's digest"

        unauthorized = await client.delete(f"/api/sources/{source_id}")
        assert unauthorized.status_code == 401
        deleted = await client.delete(f"/api/sources/{source_id}", headers={"X-API-Key": "admin-secret"})
        assert deleted.status_code == 204

    await engine.dispose()


@pytest.mark.asyncio
async def test_source_mutations_require_management_key() -> None:
    app = create_app(Settings(app_env="testing", admin_api_key="admin-secret"))
    app.state.settings = Settings(app_env="testing", admin_api_key="admin-secret")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/sources",
            json={"name": "Test", "url": "https://example.test/rss", "category": "AI"},
        )
    assert response.status_code == 401
