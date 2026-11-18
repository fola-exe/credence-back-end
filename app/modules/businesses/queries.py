from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.enums import CreditTransactionStatus, PaymentStatus
from app.models import CreditTransaction, Payment


def _outstanding_statement():
    paid = (
        select(
            Payment.transaction_id.label("transaction_id"),
            func.coalesce(func.sum(Payment.amount_kobo), 0).label("paid_kobo"),
        )
        .where(Payment.status == PaymentStatus.SUCCESSFUL)
        .group_by(Payment.transaction_id)
        .subquery()
    )
    return (
        select(
            CreditTransaction.debtor_id,
            func.coalesce(
                func.sum(
                    func.greatest(
                        CreditTransaction.amount_kobo
                        - func.coalesce(paid.c.paid_kobo, 0),
                        0,
                    )
                ),
                0,
            ).label("outstanding_kobo"),
        )
        .outerjoin(paid, paid.c.transaction_id == CreditTransaction.id)
        .where(
            CreditTransaction.status.notin_(
                [CreditTransactionStatus.SETTLED, CreditTransactionStatus.CANCELLED]
            )
        )
    )


def business_outstanding(session: Session, business_id: UUID) -> int:
    statement = _outstanding_statement().where(
        CreditTransaction.business_id == business_id
    )
    return int(session.execute(statement).scalar_one() or 0)


def outstanding_by_debtor(
    session: Session, business_id: UUID, debtor_ids: list[UUID]
) -> dict[UUID, int]:
    if not debtor_ids:
        return {}
    statement = (
        _outstanding_statement()
        .where(
            CreditTransaction.business_id == business_id,
            CreditTransaction.debtor_id.in_(debtor_ids),
        )
        .group_by(CreditTransaction.debtor_id)
    )
    return {
        row.debtor_id: int(row.outstanding_kobo)
        for row in session.execute(statement).all()
    }


def debtor_outstanding(session: Session, business_id: UUID, debtor_id: UUID) -> int:
    return outstanding_by_debtor(session, business_id, [debtor_id]).get(debtor_id, 0)
