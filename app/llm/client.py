"""Provider-agnostic LLM client interfaces and error types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.schemas import LLMResponse

SchemaT = TypeVar("SchemaT", bound=BaseModel)
ChatMessage = dict[str, Any]
ToolDefinition = dict[str, Any]


class LLMError(Exception):
    """Base exception exposed by the LLM boundary."""


class LLMConfigurationError(LLMError):
    """The provider cannot be initialized from the current configuration."""


class LLMTimeoutError(LLMError):
    """An upstream LLM call timed out after retries."""


class LLMRateLimitError(LLMError):
    """An upstream LLM provider returned HTTP 429 after retries."""


class LLMServiceError(LLMError):
    """An upstream LLM provider had a retryable or unexpected failure."""


class LLMInvalidResponseError(LLMError):
    """The provider response was empty, malformed, or failed schema validation."""


class LLMRefusalError(LLMError):
    """The model explicitly refused the requested operation."""


class LLMClient(ABC):
    """Stable async interface consumed by application services."""

    @abstractmethod
    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        json_mode: bool = False,
        tools: list[ToolDefinition] | None = None,
    ) -> LLMResponse:
        """Generate one completion from an explicit message history."""

    async def complete_structured(self, messages: list[ChatMessage], schema: type[SchemaT]) -> SchemaT:
        """Generate JSON then validate it through the supplied Pydantic schema."""

        import json

        response = await self.complete(messages, json_mode=True)
        try:
            payload = json.loads(response.content)
        except (json.JSONDecodeError, TypeError) as exc:
            raise LLMInvalidResponseError("LLM response is not valid JSON") from exc
        try:
            return schema.model_validate(payload)
        except ValidationError as exc:
            # Pydantic's ValidationError is intentionally translated so callers
            # only need one provider-boundary exception type.
            raise LLMInvalidResponseError("LLM JSON did not match the expected schema") from exc
