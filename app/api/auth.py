"""Authentication dependencies for public HTTP routes."""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Request, status


def require_admin_api_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    """Require the configured management key outside development/testing."""

    settings = request.app.state.settings
    expected = settings.admin_api_key
    if expected is None:
        if settings.app_env in {"development", "testing"}:
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Management API authentication is not configured",
        )
    if x_api_key is None or not secrets.compare_digest(x_api_key, expected.get_secret_value()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def require_wechat_webhook_token(
    request: Request,
    x_wechat_webhook_token: str | None = Header(default=None),
) -> None:
    """Require the dedicated inbound WeChat gateway token."""

    expected = request.app.state.settings.wechat_webhook_token
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WeChat webhook is not configured",
        )
    if x_wechat_webhook_token is None or not secrets.compare_digest(
        x_wechat_webhook_token,
        expected.get_secret_value(),
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook token")


__all__ = ["require_admin_api_key", "require_wechat_webhook_token"]
