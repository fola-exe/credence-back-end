from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.time import today_wat
from app.db.enums import CreditTransactionStatus, DebtorResponseType, PaymentStatus, PromiseStatus
from app.models import Business, CreditTransaction, Debtor, DebtorResponse, Payment
from app.modules.transactions.balance import balance_for, display_status


def initials(name: str) -> str:
    parts = [part for part in name.split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "?"


def receipt_url(token: str, receipt_number: str) -> str:
    return f"/public/tx/{token}/receipts/{receipt_number}"


def open_promise(db: Session, transaction_id) -> DebtorResponse | None:
    return db.execute(
        select(DebtorResponse).where(
            DebtorResponse.transaction_id == transaction_id,
            DebtorResponse.type == DebtorResponseType.PROMISE,
            DebtorResponse.promise_status == PromiseStatus.OPEN,
        )
    ).scalars().first()


def open_dispute(db: Session, transaction_id) -> DebtorResponse | None:
    return db.execute(
        select(DebtorResponse).where(
            DebtorResponse.transaction_id == transaction_id,
            DebtorResponse.type == DebtorResponseType.DISPUTE,
            DebtorResponse.resolved_at.is_(None),
        )
    ).scalars().first()


def public_transaction(db: Session, transaction: CreditTransaction) -> dict:
    balance = balance_for(db, transaction)
    business = db.get(Business, transaction.business_id)
    debtor = db.get(Debtor, transaction.debtor_id)
    today = today_wat()
    terminal = transaction.status in (
        CreditTransactionStatus.SETTLED,
        CreditTransactionStatus.CANCELLED,
    )
    message = None
    if transaction.status == CreditTransactionStatus.SETTLED:
        message = "This invoice is settled. Thank you."
    elif transaction.status == CreditTransactionStatus.CANCELLED:
        message = "This invoice was cancelled."

    promise = open_promise(db, transaction.id)
    dispute = open_dispute(db, transaction.id)
    payments = db.execute(
        select(Payment)
        .where(
            Payment.transaction_id == transaction.id,
            Payment.status == PaymentStatus.SUCCESSFUL,
        )
        .order_by(Payment.paid_at.desc())
    ).scalars().all()

    return {
        "creditor": {
            "name": business.name,
            "logo_url": business.logo_url,
            "initials": initials(business.name),
            "email": business.email,
        },
        "transaction": {
            "reference": transaction.reference,
            "invoice_number": transaction.invoice_number,
            "description": transaction.description,
            "amount_kobo": transaction.amount_kobo,
            "paid_kobo": balance.paid_kobo,
            "outstanding_kobo": balance.outstanding_kobo,
            "issue_date": transaction.issue_date,
            "due_date": transaction.due_date,
            "status": transaction.status.value,
            "display_status": display_status(
                transaction, balance.outstanding_kobo, today
            ).value,
            "days_overdue": (
                max((today - transaction.due_date).days, 0)
                if balance.outstanding_kobo > 0
                else 0
            ),
            "actions": {
                "can_pay": not terminal and balance.outstanding_kobo > 0,
                "can_promise": not terminal,
                "can_dispute": not terminal and dispute is None,
                "read_only_message": message,
            },
        },
        "open_promise": (
            {
                "promised_date": promise.promised_date,
                "promised_amount_kobo": promise.promised_amount_kobo,
            }
            if promise is not None
            else None
        ),
        "open_dispute": (
            {
                "reason": dispute.dispute_reason.value,
                "message": dispute.message,
                "created_at": dispute.created_at,
            }
            if dispute is not None
            else None
        ),
        "payments": [
            {
                "amount_kobo": payment.amount_kobo,
                "paid_at": payment.paid_at,
                "receipt_number": payment.receipt_number,
                "receipt_url": receipt_url(transaction.public_token, payment.receipt_number),
            }
            for payment in payments
        ],
        "payment_config": {
            "min_amount_kobo": 10_000,
            "currency": "NGN",
            "provider_mode": settings.provider_mode,
        },
    }
