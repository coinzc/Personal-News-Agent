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
    timezone: str = "Asia/Shanghai"
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
    enable_scheduler: bool = False
    news_collection_interval_minutes: int = Field(default=30, ge=5, le=1_440)
    message_channel: Literal["wechat", "wecom_group_bot"] = "wechat"
    wechat_gateway_endpoint: str | None = None
    wechat_gateway_token: SecretStr | None = None
    wechat_recipient: str | None = None
    wechat_webhook_token: SecretStr | None = None
    wechat_message_max_chars: int = Field(default=3500, ge=100, le=20_000)
    wechat_app_id: str | None = None
    wechat_app_secret: SecretStr | None = None
    wecom_group_bot_webhook: SecretStr | None = None
    wecom_message_type: Literal["text", "markdown"] = "markdown"
    wecom_message_max_chars: int = Field(default=3000, ge=100, le=20_000)
    wecom_timeout: float = Field(default=15.0, gt=0.0)
    wecom_max_retries: int = Field(default=3, ge=0, le=10)
    wecom_backoff_factor: float = Field(default=0.5, ge=0.0)
    admin_api_key: SecretStr | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one cached, validated settings instance per process."""

    return Settings()
