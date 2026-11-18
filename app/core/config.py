from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    jwt_secret_key: str
    jwt_token_expiry_minutes: int = 30
    jwt_algorithm: str = "HS256"

    environment: Literal["development", "staging", "production"] = "development"
    app_url: str = "http://localhost:5173"
    cors_origins: list[str] = Field(default_factory=list)
    log_level: str = "INFO"

    kora_secret_key: str = ""
    kora_base_url: str = "https://api.korapay.com/merchant/api/v1"
    kora_timeout_seconds: int = 10
    kora_mode: Literal["sandbox", "live"] = "sandbox"

    resend_api_key: str = ""
    email_from: str = "Credence <no-reply@credence.ng>"
    email_reply_to_fallback: str = "ops@credence.ng"

    receipt_pdf_enabled: bool = True
    public_rate_limit_per_minute: int = 60
    pay_rate_limit_per_minute: int = 5
    manual_reminder_cooldown_minutes: int = 60
    demo_mode: bool = False

    internal_job_token: str | None = None
    sentry_dsn: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
