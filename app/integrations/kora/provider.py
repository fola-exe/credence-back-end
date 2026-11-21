import json
from typing import Any, Protocol

import httpx

from app.core.config import Settings, settings
from app.core.money import kobo_to_naira
from app.core.time import now_utc
from app.integrations.kora.signature import canonical_data, sign


class KoraProviderError(Exception):
    pass


class KoraProvider(Protocol):
    def initialize(
        self,
        *,
        amount_kobo: int,
        reference: str,
        customer: dict[str, str],
        redirect_url: str,
        notification_url: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]: ...

    def verify(self, reference: str, *, payment: Any = None) -> dict[str, Any]: ...


class RealKoraProvider:
    def __init__(self, config: Settings | None = None) -> None:
        self.config = config or settings

    def initialize(
        self,
        *,
        amount_kobo: int,
        reference: str,
        customer: dict[str, str],
        redirect_url: str,
        notification_url: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "amount": str(kobo_to_naira(amount_kobo)),
            "currency": "NGN",
            "reference": reference,
            "narration": f"Credence credit {reference}",
            "customer": customer,
            "redirect_url": redirect_url,
            "channels": ["card", "bank_transfer", "ussd"],
            "metadata": metadata,
        }
        configured = self.config.kora_notification_url or notification_url
        if configured:
            payload["notification_url"] = configured
        try:
            response = httpx.post(
                f"{self.config.kora_base_url}/charges/initialize",
                headers={
                    "Authorization": f"Bearer {self.config.kora_secret_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.config.kora_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise KoraProviderError("Kora could not be reached") from exc
        if not response.is_success:
            raise KoraProviderError(f"Kora returned {response.status_code}")
        return response.json()

    def verify(self, reference: str, *, payment: Any = None) -> dict[str, Any]:
        try:
            response = httpx.get(
                f"{self.config.kora_base_url}/charges/{reference}",
                headers={"Authorization": f"Bearer {self.config.kora_secret_key}"},
                timeout=self.config.kora_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise KoraProviderError("Kora could not be reached") from exc
        if not response.is_success:
            raise KoraProviderError(f"Kora returned {response.status_code}")
        return response.json()


class DemoKoraProvider:
    def __init__(self, config: Settings | None = None) -> None:
        self.config = config or settings

    def initialize(
        self,
        *,
        amount_kobo: int,
        reference: str,
        customer: dict[str, str],
        redirect_url: str,
        notification_url: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "status": True,
            "message": "Demo charge initialized",
            "data": {
                "reference": reference,
                "checkout_url": f"{self.config.app_url}/demo/charges/{reference}",
                "amount": str(kobo_to_naira(amount_kobo)),
                "currency": "NGN",
                "status": "pending",
                "customer": customer,
                "redirect_url": redirect_url,
                "notification_url": notification_url,
                "metadata": metadata,
                "demo": True,
                "ttl_minutes": self.config.kora_checkout_ttl_minutes,
            },
        }

    def verify(self, reference: str, *, payment: Any = None) -> dict[str, Any]:
        marker = (payment.raw_webhook or {}).get("demo") if payment is not None else None
        if marker is None or marker.get("outcome") != "success":
            return {
                "status": True,
                "message": "Charge is pending",
                "data": {"reference": reference, "status": "pending", "currency": "NGN"},
            }
        return {
            "status": True,
            "message": "Charge verified",
            "data": {
                "reference": reference,
                "status": "success",
                "amount": marker.get("amount"),
                "currency": "NGN",
                "paid_at": marker.get("paid_at"),
            },
        }

    def make_webhook(
        self, reference: str, amount_kobo: int, outcome: str
    ) -> tuple[bytes, str]:
        data = {
            "reference": reference,
            "status": "success" if outcome == "success" else "failed",
            "amount": str(kobo_to_naira(amount_kobo)),
            "currency": "NGN",
            "fee": 0,
            "payment_method": "card",
            "transaction_date": now_utc().isoformat(),
            "demo": {
                "outcome": outcome,
                "amount": str(kobo_to_naira(amount_kobo)),
                "paid_at": now_utc().isoformat(),
            },
        }
        payload = {"event": f"charge.{data['status']}", "data": data}
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return raw, sign(canonical_data(raw), self.config.kora_signing_secret)
