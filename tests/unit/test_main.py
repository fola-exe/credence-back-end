from starlette.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.main import app


def test_cors_origins_come_from_settings():
    cors_middleware = [
        middleware
        for middleware in app.user_middleware
        if middleware.cls is CORSMiddleware
    ]

    assert len(cors_middleware) == 1
    assert cors_middleware[0].kwargs["allow_origins"] == settings.cors_origins
