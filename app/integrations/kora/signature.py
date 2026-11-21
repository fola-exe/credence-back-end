import hashlib
import hmac
import json
import re

from app.core.errors import InvalidWebhookBody


def canonical_data(raw: bytes) -> bytes:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidWebhookBody() from exc
    if not isinstance(payload, dict) or "data" not in payload:
        raise InvalidWebhookBody()
    data = payload["data"]
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def raw_data_slice(raw: bytes) -> bytes | None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidWebhookBody() from exc
    key = re.search(r'"data"\s*:\s*', text)
    if key is None:
        return None
    start = key.end()
    if start >= len(text) or text[start] != "{":
        return None
    try:
        _, end = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError as exc:
        raise InvalidWebhookBody() from exc
    return text[start:end].encode("utf-8")


def sign(data: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), data, hashlib.sha256).hexdigest()


def matching_strategy(
    raw: bytes, header: str | None, secret: str, strategy: str = ""
) -> str | None:
    if not header:
        return None
    for name in ("raw", "canonical"):
        if strategy and strategy != name:
            continue
        data = raw_data_slice(raw) if name == "raw" else canonical_data(raw)
        if data is None:
            continue
        if hmac.compare_digest(sign(data, secret), header):
            return name
    return None


def verify_signature(
    raw: bytes, header: str | None, secret: str, strategy: str = ""
) -> bool:
    return matching_strategy(raw, header, secret, strategy) is not None
