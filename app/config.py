"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
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
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    wechat_app_id: str | None = None
    wechat_app_secret: SecretStr | None = None
    admin_api_key: SecretStr | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one cached, validated settings instance per process."""

    return Settings()
