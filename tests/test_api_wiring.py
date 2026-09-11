from types import SimpleNamespace

from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def test_agent_route_returns_503_when_not_configured() -> None:
    app = create_app(Settings(database_url="sqlite+aiosqlite:///./test.db"))
    with TestClient(app) as client:
        response = client.post("/api/agent/chat", json={"message": "今天有什么新闻？"})
    assert response.status_code == 503


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
