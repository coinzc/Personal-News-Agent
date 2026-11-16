"""API smoke tests for Phase 1."""

from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


class FakeSession:
    async def execute(self, statement) -> None:
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class FakeRedis:
    async def ping(self) -> bool:
        return True


class ReadyContainer:
    session_factory = FakeSession
    redis = FakeRedis()


def test_health_endpoint_returns_service_metadata() -> None:
    settings = Settings(app_env="testing", app_name="Test News Agent")
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Test News Agent",
        "version": "0.1.0",
        "environment": "testing",
        "timezone": "Asia/Shanghai",
    }


def test_openapi_document_is_available() -> None:
    with TestClient(create_app(Settings(app_env="testing"))) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/health" in response.json()["paths"]
    assert "/ready" in response.json()["paths"]


def test_readiness_returns_ok_when_dependencies_are_available() -> None:
    app = create_app(Settings(app_env="testing"))
    with TestClient(app) as client:
        app.state.container = ReadyContainer()
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["checks"] == {"database": "ok", "redis": "ok"}


def test_readiness_returns_503_when_redis_is_unavailable() -> None:
    class BrokenRedis:
        async def ping(self) -> bool:
            raise ConnectionError("redis unavailable")

    class BrokenContainer(ReadyContainer):
        redis = BrokenRedis()

    app = create_app(Settings(app_env="testing"))
    with TestClient(app) as client:
        app.state.container = BrokenContainer()
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["database"] == "ok"
    assert response.json()["checks"]["redis"] == "failed"
