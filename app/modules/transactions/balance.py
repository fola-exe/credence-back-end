from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.enums import CreditTransactionStatus, DisplayStatus
from app.models import CreditTransaction, Payment
from app.db.enums import PaymentStatus


@dataclass(frozen=True)
class Balance:
    amount_kobo: int
    paid_kobo: int
    outstanding_kobo: int
    overpaid_kobo: int
    progress_pct: int


def calculate_balance(amount_kobo: int, paid_kobo: int) -> Balance:
    return Balance(
        amount_kobo=amount_kobo,
        paid_kobo=paid_kobo,
        outstanding_kobo=max(amount_kobo - paid_kobo, 0),
        overpaid_kobo=max(paid_kobo - amount_kobo, 0),
        progress_pct=min(100, round(paid_kobo * 100 / amount_kobo)),
    )


def paid_kobo(db: Session, transaction_id: UUID) -> int:
    return int(
        db.execute(
            select(func.coalesce(func.sum(Payment.amount_kobo), 0)).where(
                Payment.transaction_id == transaction_id,
                Payment.status == PaymentStatus.SUCCESSFUL,
            )
        ).scalar_one()
        or 0
    )


def balance_for(db: Session, transaction: CreditTransaction) -> Balance:
    return calculate_balance(transaction.amount_kobo, paid_kobo(db, transaction.id))


def display_status(
    transaction: CreditTransaction, balance_kobo: int, today: date
) -> DisplayStatus:
    if transaction.status == CreditTransactionStatus.CANCELLED:
        return DisplayStatus.CANCELLED
    if transaction.status == CreditTransactionStatus.SETTLED:
        return DisplayStatus.SETTLED
    if transaction.status == CreditTransactionStatus.DISPUTED:
        return DisplayStatus.DISPUTED
    if balance_kobo > 0 and transaction.due_date < today:
        return DisplayStatus.OVERDUE
    status_value = (
        "pending"
        if transaction.status == CreditTransactionStatus.PENDING_ACK
        else transaction.status.value
    )
    return DisplayStatus(status_value)
