from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response

from app.core.config import settings
from app.core.dependencies import AuthenticatedBusiness, DatabaseSession
from app.core.database import get_db
from app.core.errors import NotFound, UnsupportedFormat
from app.core.rate_limit import limiter
from app.modules.payments.receipts import ReceiptService
from app.modules.payments.service import PaymentService
from app.modules.public.schemas import DemoChargeRequest

payment_routes = APIRouter(tags=["payments"])

RECEIPT_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex",
}


def _apply_headers(response: Response) -> None:
    for key, value in RECEIPT_HEADERS.items():
        response.headers[key] = value


def _check_format(fmt: str) -> None:
    if fmt not in ("html", "pdf"):
        raise UnsupportedFormat()


@payment_routes.post("/webhooks/kora")
async def kora_webhook(
    request: Request,
    response: Response,
    db=Depends(get_db),
    signature: str | None = Header(default=None, alias="x-korapay-signature"),
):
    outcome = PaymentService.process_webhook(db, await request.body(), signature)
    response.headers["X-Webhook-Outcome"] = outcome
    return {"status": "ok"}


@payment_routes.post("/demo/charges/{reference}")
def demo_charge(
    payload: DemoChargeRequest,
    reference: str,
    db: DatabaseSession,
):
    outcome = PaymentService.process_demo_charge(db, reference, payload.outcome)
    return {"status": "ok", "outcome": outcome}


@payment_routes.get("/transactions/{transaction_id}/payments/{payment_id}/receipt")
def creditor_receipt(
    transaction_id: UUID,
    payment_id: UUID,
    db: DatabaseSession,
    business: AuthenticatedBusiness,
    format: str = "html",
):
    _check_format(format)
    transaction, payment = ReceiptService.for_transaction(
        db, transaction_id, payment_id
    )
    if transaction.business_id != business.id:
        raise NotFound("Receipt not found.")
    content, media_type, filename = ReceiptService.render(db, payment, format)
    headers = {}
    if filename:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(content=content, media_type=media_type, headers=headers)


@payment_routes.get("/public/tx/{token}/receipts/{receipt_number}")
@limiter.limit(f"{settings.public_rate_limit_per_minute}/minute")
def public_receipt(
    token: str,
    receipt_number: str,
    request: Request,
    response: Response,
    db=Depends(get_db),
    format: str = "html",
):
    _apply_headers(response)
    _check_format(format)
    payment = ReceiptService.for_token(db, token, receipt_number)
    content, media_type, filename = ReceiptService.render(db, payment, format)
    headers = dict(RECEIPT_HEADERS)
    if filename:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(content=content, media_type=media_type, headers=headers)
