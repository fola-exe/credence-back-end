from datetime import date
from uuid import UUID

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.db.enums import CreditTransactionStatus, DebtorResponseType, PaymentStatus, PromiseStatus
from app.models import CreditTransaction, DebtorResponse, Payment


def _paid_subquery():
    return (
        select(
            Payment.transaction_id.label("transaction_id"),
            func.coalesce(func.sum(Payment.amount_kobo), 0).label("paid_kobo"),
        )
        .where(Payment.status == PaymentStatus.SUCCESSFUL)
        .group_by(Payment.transaction_id)
        .subquery()
    )


def debtor_money_by_ids(
    session: Session, business_id: UUID, debtor_ids: list[UUID], today: date
) -> dict[UUID, dict[str, int]]:
    if not debtor_ids:
        return {}
    paid = _paid_subquery()
    remaining = func.greatest(
        CreditTransaction.amount_kobo - func.coalesce(paid.c.paid_kobo, 0), 0
    )
    statement = (
        select(
            CreditTransaction.debtor_id,
            func.coalesce(func.sum(remaining), 0).label("outstanding_kobo"),
            func.coalesce(
                func.sum(
                    case(
                        (CreditTransaction.due_date < today, remaining),
                        else_=0,
                    )
                ),
                0,
            ).label("overdue_kobo"),
        )
        .outerjoin(paid, paid.c.transaction_id == CreditTransaction.id)
        .where(
            CreditTransaction.business_id == business_id,
            CreditTransaction.status.notin_(
                [CreditTransactionStatus.SETTLED, CreditTransactionStatus.CANCELLED]
            ),
            CreditTransaction.debtor_id.in_(debtor_ids),
        )
        .group_by(CreditTransaction.debtor_id)
    )
    return {
        row.debtor_id: {
            "outstanding_kobo": int(row.outstanding_kobo),
            "overdue_kobo": int(row.overdue_kobo),
        }
        for row in session.execute(statement).all()
    }


def debtor_flags_by_ids(
    session: Session, business_id: UUID, debtor_ids: list[UUID]
) -> dict[UUID, dict[str, int | bool]]:
    if not debtor_ids:
        return {}
    statement = (
        select(
            CreditTransaction.debtor_id,
            func.count(
                func.distinct(
                    case(
                        (
                            and_(
                                DebtorResponse.type == DebtorResponseType.DISPUTE,
                                DebtorResponse.resolved_at.is_(None),
                            ),
                            DebtorResponse.id,
                        ),
                        else_=None,
                    )
                )
            ).label("open_disputes"),
            func.coalesce(
                func.bool_or(
                    and_(
                        DebtorResponse.type == DebtorResponseType.PROMISE,
                        DebtorResponse.promise_status == PromiseStatus.OPEN,
                    )
                ),
                False,
            ).label("has_open_promise"),
        )
        .join(CreditTransaction, DebtorResponse.transaction_id == CreditTransaction.id)
        .where(
            CreditTransaction.business_id == business_id,
            CreditTransaction.debtor_id.in_(debtor_ids),
        )
        .group_by(CreditTransaction.debtor_id)
    )
    return {
        row.debtor_id: {
            "open_disputes": int(row.open_disputes),
            "has_open_promise": bool(row.has_open_promise),
        }
        for row in session.execute(statement).all()
    }
