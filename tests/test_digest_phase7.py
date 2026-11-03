from datetime import UTC, date, datetime

import pytest
from app.channels.digest_delivery import DigestDeliveryService
from app.db.base import Base
from app.llm.client import LLMInvalidResponseError
from app.models import DailyDigest, NewsItem, NewsSource, User
from app.services.digest_service import DailyDigestService, DigestGenerationError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


async def make_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'digest.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


@pytest.mark.asyncio
async def test_daily_digest_generates_all_sections_and_is_idempotent(tmp_path):
    engine = await make_session(tmp_path)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = User(display_name="Digest user")
        source = NewsSource(name="Test", url="https://example.test/rss", source_type="rss", category="AI")
        session.add_all([user, source])
        await session.flush()
        item = NewsItem(
            source_id=source.id,
            title="AI model release",
            url="https://example.test/a",
            category="AI",
            language="en",
            summary="A new model was released.",
            published_at=datetime(2026, 9, 10, 2, 0, tzinfo=UTC),
        )
        session.add(item)
        await session.commit()
        service = DailyDigestService(session, user_id=user.id, timezone="Asia/Shanghai")
        digest = await service.generate_daily_digest(date(2026, 9, 10))
        same = await service.generate_daily_digest(date(2026, 9, 10))
        assert digest.status == "completed"
        assert digest.id == same.id
        assert "## AI" in digest.content
        assert "https://example.test/a" in digest.content
        assert "时间：2026-09-10 10:00" in digest.content
        assert "为什么重要" not in digest.content
        assert set(digest.sections["categories"]) == {"AI", "科技", "编程", "财经", "商业", "国际", "科学"}
    await engine.dispose()


@pytest.mark.asyncio
async def test_daily_digest_uses_chinese_llm_title_and_summary(tmp_path):
    engine = await make_session(tmp_path)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = User(display_name="Chinese digest")
        source = NewsSource(name="Test", url="https://example.test/chinese", source_type="rss", category="AI")
        session.add_all([user, source])
        await session.flush()
        session.add(
            NewsItem(
                source_id=source.id,
                title="OpenAI announces new model",
                url="https://example.test/chinese/article",
                category="AI",
                language="en",
                summary="OpenAI announced a new model.",
                published_at=datetime(2026, 9, 10, 2, 0, tzinfo=UTC),
            )
        )
        await session.commit()

        async def translated_summary(item):
            return {"title_zh": "OpenAI 发布新模型", "summary_zh": "OpenAI 发布了一款新模型。"}

        service = DailyDigestService(
            session,
            user_id=user.id,
            timezone="Asia/Shanghai",
            summarize=translated_summary,
        )
        digest = await service.generate_daily_digest(date(2026, 9, 10))
        assert "### OpenAI 发布新模型" in digest.content
        assert "摘要：OpenAI 发布了一款新模型。" in digest.content
    await engine.dispose()


@pytest.mark.asyncio
async def test_daily_digest_empty_news_still_completes(tmp_path):
    engine = await make_session(tmp_path)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = User(display_name="Empty")
        session.add(user)
        await session.commit()
        digest = await DailyDigestService(session, user_id=user.id).generate_daily_digest(date(2026, 9, 10))
        assert digest.status == "completed"
        assert all(not rows for rows in digest.sections["categories"].values())
    await engine.dispose()


@pytest.mark.asyncio
async def test_daily_digest_summarizer_failure_records_failed_task(tmp_path):
    engine = await make_session(tmp_path)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = User(display_name="Failure")
        source = NewsSource(name="Test", url="https://example.test/fail", source_type="rss", category="AI")
        session.add_all([user, source])
        await session.flush()
        session.add(
            NewsItem(
                source_id=source.id,
                title="Failure item",
                url="https://example.test/f",
                category="AI",
                language="en",
                published_at=datetime(2026, 9, 10, tzinfo=UTC),
            )
        )
        await session.commit()

        async def broken_summary(item):
            raise RuntimeError("DeepSeek unavailable")

        service = DailyDigestService(session, user_id=user.id, summarize=broken_summary)
        with pytest.raises(DigestGenerationError):
            await service.generate_daily_digest(date(2026, 9, 10))
        failed = await session.get(
            DailyDigest, (await session.execute(__import__("sqlalchemy").select(DailyDigest))).scalars().first().id
        )
        assert failed.status == "failed"
    await engine.dispose()


@pytest.mark.asyncio
async def test_daily_digest_falls_back_on_invalid_summary_json(tmp_path):
    engine = await make_session(tmp_path)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = User(display_name="Malformed summary")
        source = NewsSource(name="Test", url="https://example.test/fallback", source_type="rss", category="AI")
        session.add_all([user, source])
        await session.flush()
        session.add(
            NewsItem(
                source_id=source.id,
                title="Fallback headline",
                url="https://example.test/fallback/article",
                category="AI",
                language="en",
                summary="Grounded RSS summary.",
                published_at=datetime(2026, 9, 10, tzinfo=UTC),
            )
        )
        await session.commit()

        async def malformed_summary(item):
            raise LLMInvalidResponseError("LLM JSON did not match the expected schema")

        digest = await DailyDigestService(session, user_id=user.id, summarize=malformed_summary).generate_daily_digest(
            date(2026, 9, 10)
        )
        assert digest.status == "completed"
        assert "Grounded RSS summary." in digest.content
    await engine.dispose()


def test_compact_delivery_hides_empty_categories() -> None:
    digest = DailyDigest(
        digest_date=date(2026, 9, 10),
        timezone="Asia/Shanghai",
        status="completed",
        sections={
            "categories": {
                "AI": [
                    {
                        "title": "OpenAI 发布新模型",
                        "summary": "OpenAI 发布了一款新模型。",
                        "published_at": "2026-09-10 10:00",
                        "source_name": "OpenAI",
                        "url": "https://example.test/a",
                    }
                ],
                "科技": [],
            },
            "trend_analysis": "AI 领域持续活跃。",
        },
    )
    content = DigestDeliveryService.compact_content(digest)
    assert "AI" in content
    assert "科技" not in content
    assert "暂无重点新闻" not in content
    assert "###" not in content
    assert "为什么重要" not in content
    assert "2026-09-10 10:00" in content
    assert "原文链接" in content


def test_compact_delivery_all_empty_shows_only_overall_notice() -> None:
    digest = DailyDigest(
        digest_date=date(2026, 9, 10),
        timezone="Asia/Shanghai",
        status="completed",
        sections={"categories": {"AI": [], "游戏": []}, "trend_analysis": ""},
    )
    content = DigestDeliveryService.compact_content(digest)
    assert "暂无可用新闻" in content
    assert "🤖" not in content
    assert "游戏" not in content


def test_compact_delivery_rebuilds_legacy_trend_without_hidden_game() -> None:
    digest = DailyDigest(
        digest_date=date(2026, 9, 10),
        timezone="Asia/Shanghai",
        status="completed",
        sections={
            "categories": {
                "AI": [{"title": "模型发布", "summary": "摘要", "url": "https://example.test/a"}],
                "游戏": [],
            },
            "trend_analysis": "今日覆盖领域：AI、游戏。",
        },
    )
    content = DigestDeliveryService.compact_content(digest)
    assert "今日覆盖领域：AI。" in content
    assert "游戏" not in content


def test_compact_delivery_uses_category_emojis_and_omits_headline_and_game() -> None:
    digest = DailyDigest(
        digest_date=date(2026, 9, 10),
        timezone="Asia/Shanghai",
        status="completed",
        sections={
            "categories": {
                "AI": [
                    {
                        "title": "OpenAI 发布新模型",
                        "summary": "模型能力升级，面向开发者开放。",
                        "published_at": "2026-09-10 10:00",
                        "source_name": "OpenAI",
                        "url": "https://example.test/a",
                    }
                ],
                "游戏": [
                    {
                        "title": "游戏新闻",
                        "summary": "不应出现在日报中。",
                        "published_at": "2026-09-10 10:00",
                        "source_name": "Games",
                        "url": "https://example.test/game",
                    }
                ],
            },
            "trend_analysis": "AI 点赞数：12，评论数：3。",
        },
    )
    content = DigestDeliveryService.compact_content(digest)
    assert "🤖 AI" in content
    assert "今日头条" not in content
    assert "游戏新闻" not in content
    assert "点赞数" not in content
    assert "评论数" not in content
