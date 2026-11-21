from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

import app.main as main_module
from app.core.config import settings
from app.core.startup import StartupConfigurationError
from app.main import app


def test_cors_origins_come_from_settings():
    cors_middleware = [
        middleware
        for middleware in app.user_middleware
        if middleware.cls is CORSMiddleware
    ]

    assert len(cors_middleware) == 1
    assert cors_middleware[0].kwargs["allow_origins"] == settings.cors_origins


def test_readiness_ok(monkeypatch):
    monkeypatch.setattr(main_module, "check_database", lambda: None)

    response = TestClient(app).get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "Ready"}


def test_readiness_db_failure(monkeypatch):
    def fail():
        raise StartupConfigurationError("Cannot reach database")

    monkeypatch.setattr(main_module, "check_database", fail)

    response = TestClient(app).get("/health/ready")

    assert response.status_code == 503
