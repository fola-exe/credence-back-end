import json

from app.core.logging import (
    log_event,
    redact_public_token,
    redact_sensitive,
    setup_logging,
)


def test_redact_sensitive_handles_nested_values():
    value = {
        "public_token": "token-value",
        "pay_link": "https://example.com/pay",
        "nested": [{"token": "nested-token", "safe": "ok"}],
        "business_id": "business-id",
    }

    assert redact_sensitive(value) == {
        "public_token": "***",
        "pay_link": "***",
        "nested": [{"token": "***", "safe": "ok"}],
        "business_id": "business-id",
    }


def test_log_event_emits_structured_json(capsys):
    setup_logging("INFO")

    log_event("test_event", request_id="request-id", safe="ok", token="secret")

    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert payload["event"] == "test_event"
    assert payload["request_id"] == "request-id"
    assert payload["safe"] == "ok"
    assert payload["token"] == "***"
    assert "at" in payload
