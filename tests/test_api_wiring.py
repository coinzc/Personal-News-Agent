from types import SimpleNamespace

import pytest
from app import main
from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def test_agent_route_returns_503_when_not_configured() -> None:
    app = create_app(Settings(database_url="sqlite+aiosqlite:///./test.db"))
    with TestClient(app) as client:
        response = client.post("/api/agent/chat", json={"message": "今天有什么新闻？"})
    assert response.status_code == 503


def test_management_routes_require_api_key_when_configured() -> None:
    app = create_app(Settings(database_url="sqlite+aiosqlite:///./test.db", admin_api_key="admin-secret"))
    with TestClient(app) as client:
        missing = client.post("/api/digest/generate")
        invalid = client.post("/api/digest/generate", headers={"X-API-Key": "wrong"})
    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_management_route_accepts_api_key() -> None:
    app = create_app(Settings(database_url="sqlite+aiosqlite:///./test.db", admin_api_key="admin-secret"))
    with TestClient(app) as client:
        del app.state.container
        response = client.post("/api/digest/generate", headers={"X-API-Key": "admin-secret"})
    assert response.status_code == 503


def test_digest_send_route_retries_saved_digest() -> None:
    app = create_app(Settings(database_url="sqlite+aiosqlite:///./test.db", admin_api_key="admin-secret"))

    class FakeContainer:
        delivery_available = True
        settings = SimpleNamespace(timezone="Asia/Shanghai")

        async def send_daily_digest(self, digest_date):
            assert digest_date is None
            return True

    with TestClient(app) as client:
        app.state.container = FakeContainer()
        response = client.post("/api/digest/send", headers={"X-API-Key": "admin-secret"})
    assert response.status_code == 200
    assert response.json()["sent"] is True


def test_digest_route_returns_503_when_container_is_missing() -> None:
    app = create_app(Settings(database_url="sqlite+aiosqlite:///./test.db"))
    with TestClient(app) as client:
        del app.state.container
        response = client.post("/api/digest/generate")
    assert response.status_code == 503


def test_wechat_webhook_routes_message_to_agent() -> None:
    app = create_app(Settings(database_url="sqlite+aiosqlite:///./test.db", wechat_webhook_token="hook-secret"))

    class FakeContainer:
        agent_available = True

        async def chat(self, message: str, *, session_key: str):
            assert message == "今天有什么新闻？"
            assert session_key == "wechat:wx-1"
            return SimpleNamespace(content="今日新闻", conversation_id=None)

    with TestClient(app) as client:
        app.state.container = FakeContainer()
        response = client.post(
            "/api/wechat/webhook",
            headers={"X-WeChat-Webhook-Token": "hook-secret"},
            json={"sender_id": "wx-1", "content": "今天有什么新闻？"},
        )
    assert response.status_code == 200
    assert response.json()["content"] == "今日新闻"


def test_wechat_webhook_is_closed_without_token_configuration() -> None:
    app = create_app(Settings(database_url="sqlite+aiosqlite:///./test.db"))
    with TestClient(app) as client:
        response = client.post(
            "/api/wechat/webhook",
            json={"sender_id": "wx-1", "content": "今天有什么新闻？"},
        )
    assert response.status_code == 503


def test_wechat_webhook_rejects_incorrect_token() -> None:
    app = create_app(Settings(database_url="sqlite+aiosqlite:///./test.db", wechat_webhook_token="hook-secret"))
    with TestClient(app) as client:
        response = client.post(
            "/api/wechat/webhook",
            headers={"X-WeChat-Webhook-Token": "wrong"},
            json={"sender_id": "wx-1", "content": "今天有什么新闻？"},
        )
    assert response.status_code == 401


def test_production_requires_management_api_key() -> None:
    try:
        create_app(Settings(app_env="production", database_url="sqlite+aiosqlite:///./test.db"))
    except ValueError as exc:
        assert "ADMIN_API_KEY" in str(exc)
    else:
        raise AssertionError("production app without ADMIN_API_KEY must fail")


def test_app_lifespan_disposes_database_engine_after_container_close(monkeypatch) -> None:
    calls: list[str] = []

    class FakeContainer:
        async def aclose(self) -> None:
            calls.append("container")

    async def dispose() -> None:
        calls.append("database")

    monkeypatch.setattr(main.ApplicationContainer, "from_settings", lambda settings: FakeContainer())
    monkeypatch.setattr(main, "dispose_engine", dispose)
    with TestClient(create_app(Settings(app_env="testing"))):
        pass

    assert calls == ["container", "database"]


def test_app_lifespan_disposes_database_engine_if_container_close_fails(monkeypatch) -> None:
    calls: list[str] = []

    class FakeContainer:
        async def aclose(self) -> None:
            calls.append("container")
            raise RuntimeError("container close failed")

    async def dispose() -> None:
        calls.append("database")

    monkeypatch.setattr(main.ApplicationContainer, "from_settings", lambda settings: FakeContainer())
    monkeypatch.setattr(main, "dispose_engine", dispose)
    with pytest.raises(RuntimeError, match="container close failed"):
        with TestClient(create_app(Settings(app_env="testing"))):
            pass

    assert calls == ["container", "database"]
