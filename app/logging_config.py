"""Structured application logging setup."""

import sys

from loguru import logger

from app.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure Loguru once for console output."""

    logger.remove()
    logger.add(
        sys.stdout,
        level=settings.log_level.upper(),
        enqueue=True,
        backtrace=settings.debug,
        diagnose=settings.debug,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | {name}:{function}:{line} - {message}",
    )


__all__ = ["configure_logging", "logger"]
