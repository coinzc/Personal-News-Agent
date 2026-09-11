"""Application-level dependency composition and lifecycle ownership."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from redis.asyncio import Redis, from_url
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent import NewsAgent, SQLAlchemyConversationMemory, build_news_tool_registry
from app.channels import WeChatAdapter
from app.config import Settings
from app.db.session import get_session_factory
from app.llm import DeepSeekClient, LLMClient
from app.models import User
from app.services import DailyDigestService, NewsRanker, NewsSummarizer, SQLAlchemyNewsToolService

logger = logging.getLogger(__name__)
_DEFAULT_USER_NAME = "Personal News Agent"


class ApplicationContainer:
    """Own shared transports and construct request-scoped application services."""

    def __init__(
        self,
        settings: Settings,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        redis_client: Redis[Any] | None = None,
        llm_client: LLMClient | None = None,
        wechat: WeChatAdapter | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory or get_session_factory()
        self.redis = redis_client or from_url(settings.redis_url, decode_responses=True)
        self.llm = llm_client
        self.wechat = wechat or WeChatAdapter(
            endpoint=settings.wechat_gateway_endpoint,
            token=settings.wechat_gateway_token.get_secret_value() if settings.wechat_gateway_token else None,
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
            backoff_factor=settings.llm_backoff_factor,
            max_chars=settings.wechat_message_max_chars,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> ApplicationContainer:
        llm: LLMClient | None = None
        if settings.deepseek_api_key is not None:
            llm = DeepSeekClient(settings=settings)
        return cls(settings, llm_client=llm)

    @property
    def agent_available(self) -> bool:
        return self.llm is not None

    async def chat(self, message: str, *, session_key: str) -> Any:
        if self.llm is None:
            raise RuntimeError("DeepSeek is not configured")
        async with self.session_factory() as session:
            user = await self._default_user(session)
            summarizer = NewsSummarizer(self.llm)
            ranker = NewsRanker(self.llm)
            tool_service = SQLAlchemyNewsToolService(session, summarizer=summarizer, ranker=ranker)
            agent = NewsAgent(
                self.llm,
                build_news_tool_registry(tool_service),
                SQLAlchemyConversationMemory(session, user.id, channel="api"),
            )
            return await agent.handle(message, session_key=session_key)

    async def generate_daily_digest(self, digest_date: date | None = None) -> Any:
        async with self.session_factory() as session:
            user = await self._default_user(session)
            summary_step: Callable[[Any], Awaitable[dict[str, Any]]] | None = None
            if self.llm is not None:
                summarizer = NewsSummarizer(self.llm)

                async def summarize(item: Any) -> dict[str, Any]:
                    summary = await summarizer.summarize(item)
                    return summary.model_dump(mode="json")

                summary_step = summarize
            service = DailyDigestService(
                session,
                redis=self.redis,
                user_id=user.id,
                timezone=self.settings.timezone,
                summarize=summary_step,
            )
            return await service.generate_daily_digest(digest_date)

    async def generate_and_send_daily_digest(self, digest_date: date | None = None) -> Any:
        digest = await self.generate_daily_digest(digest_date)
        if self.settings.wechat_recipient and self.settings.wechat_gateway_endpoint:
            from app.channels.digest_delivery import DigestDeliveryService

            async with self.session_factory() as session:
                persisted = await session.get(type(digest), digest.id)
                if persisted is not None:
                    await DigestDeliveryService(session, self.wechat).send_daily_digest(
                        persisted, self.settings.wechat_recipient
                    )
        return digest

    async def _default_user(self, session: AsyncSession) -> User:
        user = await session.scalar(select(User).where(User.display_name == _DEFAULT_USER_NAME))
        if user is not None:
            return user
        user = User(display_name=_DEFAULT_USER_NAME, timezone=self.settings.timezone)
        session.add(user)
        await session.flush()
        return user

    async def aclose(self) -> None:
        close = getattr(self.llm, "aclose", None)
        if close is not None:
            await close()
        close = getattr(self.redis, "aclose", None) or getattr(self.redis, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result
        logger.info("Application runtime dependencies closed")


__all__ = ["ApplicationContainer"]
