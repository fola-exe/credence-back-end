import os

import pytest

from app.core.config import Settings
from app.core import startup
from app.core.startup import StartupConfigurationError, validate_settings, validate_startup


def _settings(monkeypatch, **overrides) -> Settings:
    for key in list(os.environ):
        if key.startswith("KORA_") or key in {"APP_URL", "ENVIRONMENT", "DEMO_MODE"}:
            monkeypatch.delenv(key, raising=False)
    values = {
        "DATABASE_URL": "postgresql+psycopg://u:p@localhost:5432/db",
        "JWT_SECRET_KEY": "jwt-secret",
        "APP_URL": "https://api.example.test",
        "KORA_SECRET_KEY": "",
        "KORA_MODE": "sandbox",
        "KORA_WEBHOOK_SECRET": "",
        "KORA_DEMO_WEBHOOK_SECRET": "",
        "KORA_SIGNATURE_STRATEGY": "",
        "KORA_NOTIFICATION_URL": "",
        "KORA_REFERENCE_FORMAT": "",
        "KORA_CHECKOUT_TTL_MINUTES": "30",
        "DEMO_MODE": "false",
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setenv(key, str(value))
    return Settings(_env_file=None)


def test_demo_mode_with_real_key_is_rejected(monkeypatch):
    config = _settings(
        monkeypatch, KORA_SECRET_KEY="sk_test_key", KORA_DEMO_MODE="true"
    )

    with pytest.raises(StartupConfigurationError):
        validate_settings(config)


def test_demo_mode_with_live_mode_is_rejected(monkeypatch):
    config = _settings(monkeypatch, KORA_MODE="live")

    with pytest.raises(StartupConfigurationError):
        validate_settings(config)


def test_real_mode_requires_matching_key_prefix(monkeypatch):
    config = _settings(monkeypatch, KORA_SECRET_KEY="sk_live_key", KORA_MODE="sandbox")

    with pytest.raises(StartupConfigurationError):
        validate_settings(config)


def test_production_sandbox_requires_demo_flag(monkeypatch):
    config = _settings(
        monkeypatch,
        ENVIRONMENT="production",
        KORA_SECRET_KEY="sk_test_key",
        DEMO_MODE="false",
    )

    with pytest.raises(StartupConfigurationError):
        validate_settings(config)


def test_production_implicit_demo_provider_is_rejected(monkeypatch):
    config = _settings(monkeypatch, ENVIRONMENT="production", DEMO_MODE="false")

    with pytest.raises(StartupConfigurationError):
        validate_settings(config)


@pytest.mark.parametrize(
    "app_url",
    ["http://api.example.test", "https://api.example.test/pay", "https://"],
)
def test_non_development_requires_https_origin(monkeypatch, app_url):
    config = _settings(monkeypatch, ENVIRONMENT="staging", APP_URL=app_url)

    with pytest.raises(StartupConfigurationError, match="https origin"):
        validate_settings(config)


def test_valid_demo_configuration_passes(monkeypatch):
    config = _settings(monkeypatch, KORA_DEMO_MODE="true")

    validate_settings(config)


def test_startup_checks_database_in_development(monkeypatch):
    calls = []
    monkeypatch.setattr(startup, "check_database", lambda: calls.append(True))

    validate_startup(_settings(monkeypatch))

    assert calls == [True]
