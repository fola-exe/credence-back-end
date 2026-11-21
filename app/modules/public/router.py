from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response, status

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import ValidationFailed
from app.core.rate_limit import limiter
from app.modules.public.schemas import DisputeRequest, PayRequest, PromiseRequest
from app.modules.public.service import PublicService

public_routes = APIRouter(tags=["public"])

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex",
}


def _apply_headers(response: Response) -> None:
    for key, value in SECURITY_HEADERS.items():
        response.headers[key] = value


@public_routes.get("/public/tx/{token}")
@limiter.limit(f"{settings.public_rate_limit_per_minute}/minute")
def get_public_transaction(
    token: str, request: Request, response: Response, db=Depends(get_db)
):
    _apply_headers(response)
    return PublicService.detail(db, token)


@public_routes.post("/public/tx/{token}/acknowledge")
@limiter.limit(f"{settings.public_rate_limit_per_minute}/minute")
def acknowledge(
    token: str, request: Request, response: Response, db=Depends(get_db)
):
    _apply_headers(response)
    return PublicService.acknowledge(db, token)


@public_routes.post("/public/tx/{token}/pay")
@limiter.limit(f"{settings.pay_rate_limit_per_minute}/minute")
def pay(
    payload: PayRequest,
    token: str,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db=Depends(get_db),
):
    _apply_headers(response)
    key = None
    if idempotency_key is not None:
        try:
            key = UUID(idempotency_key)
        except ValueError as exc:
            raise ValidationFailed(
                "The request is invalid.",
                fields={"Idempotency-Key": "Must be a UUID."},
            ) from exc
    result, code = PublicService.initiate_payment(
        db, token, payload.amount_kobo, key
    )
    response.status_code = code
    return result


@public_routes.get("/public/tx/{token}/payments/{reference}")
@limiter.limit(f"{settings.public_rate_limit_per_minute}/minute")
def payment_status(
    token: str, reference: str, request: Request, response: Response, db=Depends(get_db)
):
    _apply_headers(response)
    return PublicService.payment_status(db, token, reference)


@public_routes.post("/public/tx/{token}/promise", status_code=status.HTTP_201_CREATED)
@limiter.limit(f"{settings.public_rate_limit_per_minute}/minute")
def make_promise(
    payload: PromiseRequest,
    token: str,
    request: Request,
    response: Response,
    db=Depends(get_db),
):
    _apply_headers(response)
    result, code = PublicService.make_promise(db, token, payload)
    response.status_code = code
    return result


@public_routes.post("/public/tx/{token}/dispute", status_code=status.HTTP_201_CREATED)
@limiter.limit(f"{settings.public_rate_limit_per_minute}/minute")
def create_dispute(
    payload: DisputeRequest,
    token: str,
    request: Request,
    response: Response,
    db=Depends(get_db),
):
    _apply_headers(response)
    result, code = PublicService.create_dispute(db, token, payload)
    response.status_code = code
    return result
