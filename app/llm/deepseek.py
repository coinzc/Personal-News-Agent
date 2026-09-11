"""DeepSeek implementation of the provider-neutral LLM client."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)

from app.config import Settings, get_settings
from app.llm.client import (
    ChatMessage,
    LLMClient,
    LLMConfigurationError,
    LLMRateLimitError,
    LLMRefusalError,
    LLMServiceError,
    LLMTimeoutError,
)
from app.llm.schemas import LLMResponse, LLMToolCall, TokenUsage

logger = logging.getLogger(__name__)


class DeepSeekClient(LLMClient):
    """Async DeepSeek client with bounded exponential-backoff retries.

    An SDK client can be injected for tests or for a different OpenAI-
    compatible gateway.  The API key is only read from ``SecretStr`` at
    construction time and is never included in logs or exception messages.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: AsyncOpenAI | Any | None = None,
        model: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        backoff_factor: float | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        if client is None:
            if self.settings.deepseek_api_key is None:
                raise LLMConfigurationError("DEEPSEEK_API_KEY is not configured")
            client = AsyncOpenAI(
                api_key=self.settings.deepseek_api_key.get_secret_value(),
                base_url=self.settings.deepseek_base_url,
                timeout=timeout or self.settings.llm_timeout,
                max_retries=0,
            )
        self.client = client
        self.model = model or self.settings.deepseek_model
        self.timeout = timeout or self.settings.llm_timeout
        self.max_retries = max_retries if max_retries is not None else self.settings.llm_max_retries
        self.backoff_factor = backoff_factor if backoff_factor is not None else self.settings.llm_backoff_factor
        if self.max_retries < 0 or self.backoff_factor < 0 or self.timeout <= 0:
            raise ValueError("invalid DeepSeek retry/timeout configuration")

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        json_mode: bool = False,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Call chat completions and return provider-neutral usage/latency data."""

        started = time.perf_counter()
        for attempt in range(self.max_retries + 1):
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.2,
                }
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                if tools:
                    kwargs["tools"] = tools
                    kwargs["parallel_tool_calls"] = False
                response = await self.client.chat.completions.create(**kwargs)
                choice = response.choices[0] if response.choices else None
                if choice is None or choice.message is None:
                    raise LLMServiceError("DeepSeek returned no completion choice")
                refusal = getattr(choice.message, "refusal", None)
                finish_reason = getattr(choice, "finish_reason", None)
                if refusal or finish_reason in {"refusal", "content_filter"}:
                    raise LLMRefusalError("DeepSeek refused the request")
                content = choice.message.content or ""
                raw_tool_calls = getattr(choice.message, "tool_calls", None) or []
                tool_calls: list[LLMToolCall] = []
                for raw_call in raw_tool_calls:
                    function = getattr(raw_call, "function", None)
                    if function is None:
                        continue
                    import json

                    try:
                        arguments = json.loads(getattr(function, "arguments", "{}") or "{}")
                    except (TypeError, ValueError) as exc:
                        raise LLMServiceError("DeepSeek returned invalid tool arguments") from exc
                    if not isinstance(arguments, dict):
                        raise LLMServiceError("DeepSeek returned non-object tool arguments")
                    tool_calls.append(
                        LLMToolCall(
                            id=str(getattr(raw_call, "id", "")),
                            name=str(getattr(function, "name", "")),
                            arguments=arguments,
                        )
                    )
                if not tool_calls and (not isinstance(content, str) or not content.strip()):
                    raise LLMServiceError("DeepSeek returned empty content")
                usage = getattr(response, "usage", None)
                token_usage = TokenUsage(
                    prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                    completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                    total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
                )
                latency_ms = (time.perf_counter() - started) * 1000
                logger.info(
                    "DeepSeek completion succeeded model=%s latency_ms=%.1f total_tokens=%d",
                    self.model,
                    latency_ms,
                    token_usage.total_tokens,
                )
                return LLMResponse(
                    content=content,
                    model=str(getattr(response, "model", self.model) or self.model),
                    usage=token_usage,
                    latency_ms=latency_ms,
                    finish_reason=finish_reason,
                    tool_calls=tool_calls,
                )
            except LLMRefusalError:
                raise
            except APITimeoutError as exc:
                if attempt >= self.max_retries:
                    raise LLMTimeoutError("DeepSeek request timed out") from exc
                await self._backoff(attempt)
            except RateLimitError as exc:
                if attempt >= self.max_retries:
                    raise LLMRateLimitError("DeepSeek rate limit exceeded") from exc
                await self._backoff(attempt)
            except (InternalServerError, APIConnectionError) as exc:
                if attempt >= self.max_retries:
                    raise LLMServiceError("DeepSeek upstream service unavailable") from exc
                await self._backoff(attempt)
            except APIStatusError as exc:
                status = getattr(exc, "status_code", None)
                if status == 429:
                    if attempt >= self.max_retries:
                        raise LLMRateLimitError("DeepSeek rate limit exceeded") from exc
                    await self._backoff(attempt)
                    continue
                if isinstance(status, int) and status >= 500 and attempt < self.max_retries:
                    await self._backoff(attempt)
                    continue
                raise LLMServiceError(f"DeepSeek API request failed with status {status}") from exc
            except LLMServiceError:
                raise
            except Exception as exc:
                # Keep provider internals and request headers out of logs.
                logger.error("Unexpected DeepSeek client failure type=%s", type(exc).__name__)
                raise LLMServiceError("DeepSeek request failed") from exc
        raise LLMServiceError("DeepSeek request failed after retries")

    async def _backoff(self, attempt: int) -> None:
        delay = self.backoff_factor * (2**attempt)
        if delay:
            await asyncio.sleep(delay)

    async def aclose(self) -> None:
        """Close the underlying SDK transport when it exposes ``close``."""

        close = getattr(self.client, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result
