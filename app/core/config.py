from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEMO_WEBHOOK_FALLBACK_SECRET = "credence-demo-webhook-v1"


class Settings(BaseSettings):
    database_url: str
    jwt_secret_key: str
    jwt_token_expiry_minutes: int = 30
    jwt_algorithm: str = "HS256"

    environment: Literal["development", "staging", "production"] = "development"
    app_url: str = "http://localhost:8000"
    cors_origins: list[str] = Field(default_factory=list)
    log_level: str = "INFO"

    frontend_url: str = ""

    kora_secret_key: str = ""
    kora_base_url: str = "https://api.korapay.com/merchant/api/v1"
    kora_timeout_seconds: int = 10
    kora_mode: Literal["sandbox", "live"] = "sandbox"
    kora_webhook_secret: str = ""
    kora_demo_mode: bool | None = None
    kora_demo_webhook_secret: str = ""
    kora_signature_strategy: Literal["", "raw", "canonical"] = ""
    kora_notification_url: str = ""
    kora_reference_format: str = ""
    kora_checkout_ttl_minutes: int = 30

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

    @property
    def kora_demo_enabled(self) -> bool:
        if self.kora_demo_mode is not None:
            return self.kora_demo_mode
        return not bool(self.kora_secret_key.strip())

    @property
    def kora_signing_secret(self) -> str:
        if self.kora_webhook_secret:
            return self.kora_webhook_secret
        if self.kora_demo_enabled:
            return self.kora_demo_webhook_secret or DEMO_WEBHOOK_FALLBACK_SECRET
        return self.kora_secret_key

    @property
    def provider_mode(self) -> str:
        if self.kora_demo_enabled:
            return "sandbox"
        return "live" if self.kora_mode == "live" else "sandbox"

    @property
    def user_facing_url(self) -> str:
        return self.frontend_url or self.app_url


settings = Settings()
