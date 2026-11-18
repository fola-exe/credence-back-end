from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.core.money import format_naira
from app.core.time import format_date_wat, today_wat
from app.integrations.email.render import render_email
from app.integrations.email.templates import get_template

RESEND_URL = "https://api.resend.com/emails"


class EmailError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class EmailResult:
    provider_message_id: str


class EmailService:
    def send(
        self,
        template_key: str,
        *,
        to: str,
        context: dict,
        cc: str | None = None,
    ) -> EmailResult:
        subject, body = render_email(get_template(template_key), context)
        if not settings.resend_api_key:
            raise EmailError("RESEND_API_KEY is not configured", retryable=False)

        payload = {
            "from": settings.email_from,
            "to": [to],
            "subject": subject,
            "html": body,
        }
        if cc:
            payload["cc"] = [cc]
        if settings.email_reply_to_fallback:
            payload["reply_to"] = settings.email_reply_to_fallback

        try:
            response = httpx.post(
                RESEND_URL,
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=10,
            )
        except httpx.TimeoutException as exc:
            raise EmailError("email provider timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise EmailError("email provider unavailable", retryable=True) from exc

        if response.status_code >= 500 or response.status_code == 429:
            raise EmailError("email provider rejected the request", retryable=True)
        if not response.is_success:
            raise EmailError("email was rejected", retryable=False)

        return EmailResult(provider_message_id=response.json().get("id", ""))

    def send_creditor_notice(self, tx, response_summary: str, *, to: str) -> EmailResult:
        return self.send(
            "creditor_notice",
            to=to,
            context={
                "business_name": getattr(tx, "business_name", ""),
                "debtor_name": getattr(tx, "debtor_name", ""),
                "reference": getattr(tx, "reference", ""),
                "response_summary": response_summary,
            },
        )


def build_context(tx, balance, debtor, business, **extra) -> dict:
    context = {
        "debtor_name": debtor.name,
        "business_name": business.name,
        "reference": tx.reference,
        "invoice_number": tx.invoice_number or "",
        "description": tx.description,
        "transaction_amount": format_naira(tx.amount_kobo),
        "amount_paid": format_naira(balance.paid_kobo),
        "outstanding_balance": format_naira(balance.outstanding_kobo),
        "due_date": format_date_wat(tx.due_date),
        "days_overdue": str(max((today_wat() - tx.due_date).days, 0)),
        "payment_link": f"{settings.app_url}/pay/{tx.public_token}",
        "receipt_number": "",
        "receipt_link": "",
        "response_summary": "",
    }
    context.update(extra)
    return context


email_service = EmailService()
