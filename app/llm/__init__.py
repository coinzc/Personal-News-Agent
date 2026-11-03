"""Provider-neutral LLM clients and validated news output schemas."""

from app.llm.client import (
    LLMClient,
    LLMConfigurationError,
    LLMError,
    LLMInvalidResponseError,
    LLMRateLimitError,
    LLMRefusalError,
    LLMServiceError,
    LLMTimeoutError,
)
from app.llm.deepseek import DeepSeekClient
from app.llm.schemas import (
    LLMResponse,
    LLMToolCall,
    NewsClassification,
    NewsRanking,
    NewsRankingFactors,
    NewsSummary,
    NewsTranslation,
    TokenUsage,
)

__all__ = [
    "DeepSeekClient",
    "LLMClient",
    "LLMConfigurationError",
    "LLMError",
    "LLMInvalidResponseError",
    "LLMRateLimitError",
    "LLMRefusalError",
    "LLMResponse",
    "LLMServiceError",
    "LLMTimeoutError",
    "LLMToolCall",
    "NewsClassification",
    "NewsRanking",
    "NewsRankingFactors",
    "NewsSummary",
    "NewsTranslation",
    "TokenUsage",
]
