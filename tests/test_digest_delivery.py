from __future__ import annotations

import asyncio
from datetime import date

import pytest
from app.channels.base import MessageChannel, MessageResult
from app.channels.digest_delivery import DigestDeliveryService
from app.db.base import Base
from app.models import DailyDigest, User
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class RecordingChannel(MessageChannel):
    def __init__(
        self,
        *,
        fail: bool = False,
        started: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
    ):
        self.fail = fail
        self.started = started
        self.release = release
        self.calls = 0

    async def send_text(self, recipient: str, content: str) -> MessageResult:
        self.calls += 1
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        if self.fail:
            raise RuntimeError("temporary provider failure")
        return MessageResult(provider="test")


class SharedRedisLock:
    def __init__(self) -> None:
        self.locked = False

    def lock(self, key: str, *, timeout: int, blocking: bool) -> SharedRedisLock:
        return self

    async def acquire(self, *, blocking: bool) -> bool:
        if self.locked:
            return False
        self.locked = True
        return True

    async def release(self) -> None:
        self.locked = False


async def make_digest_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'delivery.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(display_name="Delivery user")
        session.add(user)
        await session.flush()
        digest = DailyDigest(
            user_id=user.id,
            digest_date=date(2026, 9, 10),
            timezone="Asia/Shanghai",
            status="completed",
            content="digest",
            sections={"categories": {}, "trend_analysis": ""},
        )
        session.add(digest)
        await session.commit()
        digest_id = digest.id
    return engine, factory, digest_id


@pytest.mark.asyncio
async def test_sent_digest_is_not_sent_again_even_from_stale_session(tmp_path) -> None:
    engine, factory, digest_id = await make_digest_session(tmp_path)
    channel = RecordingChannel()
    async with factory() as first_session, factory() as stale_session:
        first_copy = await first_session.get(DailyDigest, digest_id)
        stale_copy = await stale_session.get(DailyDigest, digest_id)
        assert first_copy is not None and stale_copy is not None

        first_sent = await DigestDeliveryService(first_session, channel).send_daily_digest(first_copy, "default")
        duplicate_sent = await DigestDeliveryService(stale_session, channel).send_daily_digest(stale_copy, "default")

        assert first_sent is True
        assert duplicate_sent is False
        assert channel.calls == 1
        assert stale_copy.status == "sent"
    await engine.dispose()


@pytest.mark.asyncio
async def test_failed_delivery_can_be_retried_and_marked_sent(tmp_path) -> None:
    engine, factory, digest_id = await make_digest_session(tmp_path)
    async with factory() as session:
        digest = await session.get(DailyDigest, digest_id)
        assert digest is not None

        failed = await DigestDeliveryService(session, RecordingChannel(fail=True)).send_daily_digest(digest, "default")
        assert failed is False
        assert digest.status == "send_failed"
        assert "temporary provider failure" in (digest.error_message or "")

        retried = await DigestDeliveryService(session, RecordingChannel()).send_daily_digest(digest, "default")
        assert retried is True
        assert digest.status == "sent"
        assert digest.error_message is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_distributed_lock_skips_concurrent_delivery_without_changing_status(tmp_path) -> None:
    engine, factory, digest_id = await make_digest_session(tmp_path)
    redis = SharedRedisLock()
    started = asyncio.Event()
    release = asyncio.Event()
    first_channel = RecordingChannel(started=started, release=release)
    second_channel = RecordingChannel()

    async with factory() as first_session, factory() as second_session:
        first_digest = await first_session.get(DailyDigest, digest_id)
        second_digest = await second_session.get(DailyDigest, digest_id)
        assert first_digest is not None and second_digest is not None
        first_task = asyncio.create_task(
            DigestDeliveryService(first_session, first_channel, redis=redis).send_daily_digest(
                first_digest, "default"
            )
        )
        await started.wait()
        second_sent = await DigestDeliveryService(second_session, second_channel, redis=redis).send_daily_digest(
            second_digest, "default"
        )
        release.set()
        first_sent = await first_task

        assert first_sent is True
        assert second_sent is False
        assert first_channel.calls == 1
        assert second_channel.calls == 0
        assert second_digest.status == "completed"
    await engine.dispose()
