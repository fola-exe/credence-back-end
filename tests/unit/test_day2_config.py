import os

from app.core.config import DEMO_WEBHOOK_FALLBACK_SECRET, Settings


def _settings(monkeypatch, **overrides) -> Settings:
    for key in list(os.environ):
        if key.startswith("KORA_") or key in {"APP_URL", "FRONTEND_URL"}:
            monkeypatch.delenv(key, raising=False)
    values = {
        "DATABASE_URL": "postgresql+psycopg://u:p@localhost:5432/db",
        "JWT_SECRET_KEY": "jwt-secret",
        "APP_URL": "http://localhost:8000",
        "KORA_SECRET_KEY": "",
        "KORA_MODE": "sandbox",
        "KORA_WEBHOOK_SECRET": "",
        "KORA_DEMO_WEBHOOK_SECRET": "",
        "KORA_SIGNATURE_STRATEGY": "",
        "KORA_NOTIFICATION_URL": "",
        "KORA_REFERENCE_FORMAT": "",
        "KORA_CHECKOUT_TTL_MINUTES": "30",
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setenv(key, str(value))
    return Settings(_env_file=None)


def test_empty_kora_key_auto_enables_demo(monkeypatch):
    config = _settings(monkeypatch)

    assert config.kora_demo_enabled is True
    assert config.kora_signing_secret == DEMO_WEBHOOK_FALLBACK_SECRET
    assert config.kora_signing_secret != config.jwt_secret_key
    assert config.provider_mode == "sandbox"


def test_explicit_demo_webhook_secret_is_used(monkeypatch):
    config = _settings(monkeypatch, KORA_DEMO_WEBHOOK_SECRET="demo-webhook-secret")

    assert config.kora_signing_secret == "demo-webhook-secret"


def test_real_key_uses_secret_and_explicit_webhook_secret(monkeypatch):
    config = _settings(
        monkeypatch,
        KORA_SECRET_KEY="sk_live_key",
        KORA_MODE="live",
        KORA_WEBHOOK_SECRET="webhook-secret",
    )

    assert config.kora_demo_enabled is False
    assert config.kora_signing_secret == "webhook-secret"
    assert config.provider_mode == "live"


def test_explicit_demo_mode_overrides_empty_real_key(monkeypatch):
    config = _settings(monkeypatch, KORA_DEMO_MODE="true")

    assert config.kora_demo_enabled is True


def test_user_facing_url_uses_frontend_then_app(monkeypatch):
    app_only = _settings(monkeypatch, APP_URL="https://api.example.test")
    with_frontend = _settings(
        monkeypatch,
        APP_URL="https://api.example.test",
        FRONTEND_URL="https://app.example.test",
    )

    assert app_only.user_facing_url == "https://api.example.test"
    assert with_frontend.user_facing_url == "https://app.example.test"
