import os

import pytest

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://user:pass@localhost:5432/credence",
)
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")


@pytest.fixture(autouse=True)
def isolate_settings_from_dotenv(monkeypatch):
    from pydantic_settings import SettingsConfigDict

    from app.core.config import Settings

    monkeypatch.setattr(
        Settings,
        "model_config",
        SettingsConfigDict(env_file=None, extra="ignore"),
    )
