from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, settings
from app.core.database import engine


class StartupConfigurationError(Exception):
    pass


def validate_settings(config: Settings) -> None:
    if config.environment != "development":
        parsed = urlsplit(config.app_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise StartupConfigurationError("APP_URL must be an https origin")

    if config.kora_demo_enabled:
        if config.environment == "production" and config.demo_mode is not True:
            raise StartupConfigurationError(
                "Refusing to start: demo provider in production requires DEMO_MODE=true"
            )
        if config.kora_secret_key and config.kora_demo_mode is True:
            raise StartupConfigurationError(
                "KORA_DEMO_MODE=true cannot be combined with KORA_SECRET_KEY"
            )
        if config.kora_mode == "live":
            raise StartupConfigurationError("KORA_DEMO_MODE cannot be combined with a live key")
        return

    key = config.kora_secret_key
    expected_prefix = "sk_test_" if config.kora_mode == "sandbox" else "sk_live_"
    if not key.startswith(expected_prefix):
        raise StartupConfigurationError("KORA_MODE does not match the configured Kora key")

    if config.environment == "production" and config.kora_mode == "sandbox":
        if not config.demo_mode:
            raise StartupConfigurationError(
                "Refusing to start: sandbox Kora in production requires DEMO_MODE=true"
            )
    if config.demo_mode and config.kora_mode == "live":
        raise StartupConfigurationError("DEMO_MODE cannot be combined with a live Kora key")


def check_database() -> None:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise StartupConfigurationError("Cannot reach database") from exc


def validate_startup(config: Settings | None = None) -> None:
    active = config if config is not None else settings
    validate_settings(active)
    check_database()
