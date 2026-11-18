import json
import logging
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

REDACTED = "***"
SENSITIVE_KEYS = {
    "authorization",
    "access_token",
    "kora_secret_key",
    "password",
    "pay_link",
    "public_token",
    "resend_api_key",
    "secret",
    "token",
}

logger = logging.getLogger("credence")
PUBLIC_TOKEN_PATH = re.compile(r"(/public/tx/)([^/?#]+)")


def setup_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.handlers = [handler]
    logger.setLevel(level.upper())
    logger.propagate = False


def new_request_id() -> str:
    return str(uuid.uuid4())


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED
            if str(key).lower() in SENSITIVE_KEYS
            else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_sensitive(item) for item in value]
    return value


def redact_public_token(path: str) -> str:
    return PUBLIC_TOKEN_PATH.sub(r"\1{token}", path)


def _emit(namespace: str, event: str, *, request_id: str | None = None, **fields: Any) -> None:
    payload = {
        namespace: event,
        "request_id": request_id or new_request_id(),
        "at": datetime.now(timezone.utc).isoformat(),
        **redact_sensitive(fields),
    }
    logger.info(json.dumps(payload, separators=(",", ":"), sort_keys=True))


def log_event(event: str, *, request_id: str | None = None, **fields: Any) -> None:
    _emit("event", event, request_id=request_id, **fields)


def audit_event(event: str, *, request_id: str | None = None, **fields: Any) -> None:
    _emit("audit", event, request_id=request_id, **fields)
