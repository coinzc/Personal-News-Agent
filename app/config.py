"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Personal News Agent"
    app_env: Literal["development", "testing", "staging", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    timezone: str = "Asia/Singapore"
    api_prefix: str = "/api"
    database_url: str = "postgresql+asyncpg://news_agent:change-me@localhost:5432/news_agent"
    redis_url: str = "redis://localhost:6379/0"
    dedup_similarity_threshold: float = Field(default=0.78, ge=0.0, le=1.0)
    dedup_embedding_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    llm_timeout: float = Field(default=45.0, gt=0.0)
    llm_max_retries: int = Field(default=3, ge=0, le=10)
    llm_backoff_factor: float = Field(default=0.5, ge=0.0)
    wechat_app_id: str | None = None
    wechat_app_secret: SecretStr | None = None
    admin_api_key: SecretStr | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one cached, validated settings instance per process."""

    return Settings()
