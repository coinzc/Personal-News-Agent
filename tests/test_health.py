"""API smoke tests for Phase 1."""

from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


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
