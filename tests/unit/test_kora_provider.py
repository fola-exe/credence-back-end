import json
import os
from types import SimpleNamespace

import httpx
import respx

from app.core.config import Settings
from app.integrations.kora.provider import DemoKoraProvider, RealKoraProvider
from app.integrations.kora.signature import verify_signature


def _settings(monkeypatch, **overrides) -> Settings:
    for key in list(os.environ):
        if key.startswith("KORA_"):
            monkeypatch.delenv(key, raising=False)
    values = {
        "DATABASE_URL": "postgresql+psycopg://u:p@localhost:5432/db",
        "JWT_SECRET_KEY": "jwt-secret",
        "APP_URL": "http://localhost:8000",
        "KORA_SECRET_KEY": "",
        "KORA_MODE": "sandbox",
        "KORA_WEBHOOK_SECRET": "",
        "KORA_DEMO_MODE": "true",
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


def test_demo_provider_initializes_and_signs_webhook(monkeypatch):
    config = _settings(monkeypatch)
    provider = DemoKoraProvider(config)
    result = provider.initialize(
        amount_kobo=150_000,
        reference="CRD-000001-P1",
        customer={"name": "Debtor", "email": "debtor@example.test"},
        redirect_url="http://localhost:8000/pay/token/result",
        notification_url="http://localhost:8000/webhooks/kora",
        metadata={},
    )
    assert result["data"]["checkout_url"].endswith("/demo/charges/CRD-000001-P1")
    assert result["data"]["amount"] == "1500.00"

    raw, signature = provider.make_webhook("CRD-000001-P1", 150_000, "success")
    assert verify_signature(raw, signature, config.kora_signing_secret)

    pending = provider.verify("CRD-000001-P1")
    assert pending["data"]["status"] == "pending"

    payload = json.loads(raw)
    verified = provider.verify(
        "CRD-000001-P1", payment=SimpleNamespace(raw_webhook=payload["data"])
    )
    assert verified["data"]["status"] == "success"
    assert verified["data"]["amount"] == "1500.00"


def test_real_provider_calls_kora_with_naira_string(monkeypatch):
    config = _settings(
        monkeypatch, KORA_DEMO_MODE="false", KORA_SECRET_KEY="sk_test_key"
    )
    provider = RealKoraProvider(config)

    with respx.mock:
        initialize = respx.post(
            "https://api.korapay.com/merchant/api/v1/charges/initialize"
        ).mock(return_value=httpx.Response(200, json={"status": True, "data": {}}))
        result = provider.initialize(
            amount_kobo=150_000,
            reference="CRD-000001-P1",
            customer={"name": "Debtor", "email": "debtor@example.test"},
            redirect_url="https://app.example.test/result",
            notification_url="https://api.example.test/webhooks/kora",
            metadata={"transaction_id": "tx-1"},
        )
        assert result["status"] is True
        body = json.loads(initialize.calls[0].request.content)
        assert body["amount"] == "1500.00"
        assert body["reference"] == "CRD-000001-P1"

        respx.get(
            "https://api.korapay.com/merchant/api/v1/charges/CRD-000001-P1"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"status": True, "data": {"status": "success", "amount": "1500.00"}},
            )
        )
        verified = provider.verify("CRD-000001-P1")
        assert verified["data"]["amount"] == "1500.00"
