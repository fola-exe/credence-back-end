from app.core.config import Settings


def test_config_reads_environment_overrides(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.setenv("JWT_SECRET_KEY", "override-secret")
    monkeypatch.setenv("CORS_ORIGINS", '["https://app.example.com"]')
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("PUBLIC_RATE_LIMIT_PER_MINUTE", "42")

    settings = Settings()

    assert settings.database_url == "postgresql+psycopg://u:p@localhost:5432/db"
    assert settings.jwt_secret_key == "override-secret"
    assert settings.cors_origins == ["https://app.example.com"]
    assert settings.environment == "staging"
    assert settings.demo_mode is True
    assert settings.public_rate_limit_per_minute == 42


def test_config_uses_safe_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.setenv("JWT_SECRET_KEY", "default-secret")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("RECEIPT_PDF_ENABLED", raising=False)

    settings = Settings()

    assert settings.cors_origins == []
    assert settings.environment == "development"
    assert settings.kora_mode == "sandbox"
    assert settings.demo_mode is False
    assert settings.receipt_pdf_enabled is True
