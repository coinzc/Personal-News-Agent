"""Command-line database schema initializer backed by Alembic."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import get_settings
from app.logging_config import configure_logging, logger

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def build_alembic_config(database_url: str | None = None) -> Config:
    """Build an Alembic config using a validated application database URL."""

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "db" / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url or get_settings().database_url)
    return config


def initialize_database(database_url: str | None = None) -> None:
    """Upgrade the configured database to the latest schema revision."""

    settings = get_settings()
    configure_logging(settings)
    logger.info("Applying database migrations")
    command.upgrade(build_alembic_config(database_url), "head")
    logger.info("Database schema is current")


def main() -> None:
    """Run database initialization from ``python -m app.db.init_db``."""

    initialize_database()


if __name__ == "__main__":
    main()
