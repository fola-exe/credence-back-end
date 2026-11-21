from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import (
    AmountOutOfRange,
    PromiseWindowInvalid,
    TransactionNotPayable,
)
from app.core.logging import log_event
from app.core.time import WAT, at_9am_wat, now_utc, today_wat
from app.db.enums import (
    CreditTransactionStatus,
    DebtorResponseType,
    EventActor,
    PromiseStatus,
    ReminderStatus,
)
from app.integrations.email.client import email_service
from app.models import Business, CreditTransaction, Debtor, DebtorResponse, Reminder, TransactionEvent
from app.modules.transactions.balance import balance_for, display_status
from app.modules.transactions.events import record
from app.modules.public.projection import open_promise


def evaluate(promise: DebtorResponse, payments: list, today) -> str:
    window_end = promise.promised_date
    paid_in_window = sum(
        payment.amount_kobo
        for payment in payments
        if payment.paid_at is not None and payment.paid_at.astimezone(WAT).date() <= window_end
    )
    target = promise.promised_amount_kobo
    if target is None:
        return "still_open"
    if paid_in_window >= target:
        return "kept"
    if today > window_end:
        return "missed"
    return "still_open"


class PromiseService:
    @staticmethod
    def _target_kobo(db: Session, promise: DebtorResponse) -> int | None:
        if promise.promised_amount_kobo is not None:
            return promise.promised_amount_kobo
        event = db.execute(
            select(TransactionEvent).where(
                TransactionEvent.transaction_id == promise.transaction_id,
                TransactionEvent.type == "promise_made",
            ).order_by(TransactionEvent.created_at.desc())
        ).scalars().first()
        if event is None:
            return None
        return event.data.get("balance_at_promise_kobo")

    @classmethod
    def make(cls, db: Session, transaction: CreditTransaction, payload) -> tuple[dict, int]:
        locked = db.execute(
            select(CreditTransaction)
            .where(CreditTransaction.id == transaction.id)
            .with_for_update()
        ).scalars().one()
        if locked.status in (
            CreditTransactionStatus.SETTLED,
            CreditTransactionStatus.CANCELLED,
        ):
            raise TransactionNotPayable()
        today = today_wat()
        if not (today <= payload.promised_date <= today + timedelta(days=60)):
            raise PromiseWindowInvalid()
        balance = balance_for(db, locked)
        amount = payload.promised_amount_kobo or balance.outstanding_kobo
        if amount <= 0 or amount > balance.outstanding_kobo:
            raise AmountOutOfRange()

        existing = open_promise(db, locked.id)
        if existing is not None:
            age = now_utc() - existing.created_at
            if (
                age <= timedelta(minutes=5)
                and existing.promised_date == payload.promised_date
                and (existing.promised_amount_kobo or balance.outstanding_kobo) == amount
                and (existing.message or "") == (payload.message or "")
            ):
                reminder = db.execute(
                    select(Reminder).where(
                        Reminder.transaction_id == locked.id,
                        Reminder.status == ReminderStatus.SCHEDULED,
                    ).order_by(Reminder.scheduled_for)
                ).scalars().first()
                return cls._response(db, locked, existing, reminder, 200)

        if existing is not None:
            existing.promise_status = PromiseStatus.SUPERSEDED

        promise = DebtorResponse(
            transaction_id=locked.id,
            type=DebtorResponseType.PROMISE,
            promised_date=payload.promised_date,
            promised_amount_kobo=payload.promised_amount_kobo,
            message=payload.message,
            promise_status=PromiseStatus.OPEN,
        )
        db.add(promise)
        if locked.status == CreditTransactionStatus.PENDING_ACK:
            locked.status = CreditTransactionStatus.ACTIVE
            locked.acknowledged_at = now_utc()
        record(
            db,
            locked.id,
            "promise_made",
            EventActor.DEBTOR,
            {
                "promised_date": payload.promised_date.isoformat(),
                "promised_amount_kobo": payload.promised_amount_kobo,
                "balance_at_promise_kobo": balance.outstanding_kobo,
                "message": payload.message,
            },
        )
        next_reminder = db.execute(
            select(Reminder).where(
                Reminder.transaction_id == locked.id,
                Reminder.status == ReminderStatus.SCHEDULED,
            ).order_by(Reminder.scheduled_for)
        ).scalars().first()
        if next_reminder is not None:
            next_reminder.scheduled_for = at_9am_wat(
                payload.promised_date + timedelta(days=1)
            )
        db.commit()
        db.refresh(promise)
        db.refresh(locked)

        business = db.get(Business, locked.business_id)
        debtor = db.get(Debtor, locked.debtor_id)
        try:
            email_service.send(
                "creditor_notice",
                to=business.email,
                context={
                    "business_name": business.name,
                    "debtor_name": debtor.name,
                    "reference": locked.reference,
                    "response_summary": (
                        f"{debtor.name} promised to pay ₦{amount // 100:,} "
                        f"by {payload.promised_date.isoformat()}"
                    ),
                },
            )
        except Exception as exc:
            log_event(
                "email_failed",
                template="creditor_notice",
                reference=locked.reference,
                error=str(exc),
            )
        return cls._response(db, locked, promise, next_reminder, 201)

    @staticmethod
    def _response(db: Session, tx, promise, reminder, status_code: int) -> tuple[dict, int]:
        balance = balance_for(db, tx)
        return (
            {
                "promise": {
                    "id": promise.id,
                    "promised_date": promise.promised_date,
                    "promised_amount_kobo": promise.promised_amount_kobo,
                    "message": promise.message,
                    "status": promise.promise_status.value,
                    "created_at": promise.created_at,
                },
                "transaction": {
                    "status": tx.status.value,
                    "display_status": display_status(
                        tx, balance.outstanding_kobo, today_wat()
                    ).value,
                },
                "next_reminder": (
                    {"kind": reminder.kind.value, "scheduled_for": reminder.scheduled_for}
                    if reminder is not None
                    else None
                ),
            },
            status_code,
        )

    @classmethod
    def check_after_payment(
        cls, db: Session, transaction: CreditTransaction, payments: list, paid_at
    ) -> None:
        promise = open_promise(db, transaction.id)
        if promise is None:
            return
        target = cls._target_kobo(db, promise)
        if target is None:
            return
        paid_in_window = sum(
            payment.amount_kobo
            for payment in payments
            if payment.paid_at is not None and payment.paid_at.astimezone(WAT).date() <= promise.promised_date
        )
        if paid_in_window < target:
            return
        promise.promise_status = PromiseStatus.KEPT
        record(
            db,
            transaction.id,
            "promise_kept",
            EventActor.SYSTEM,
            {"promised_date": promise.promised_date.isoformat(), "amount_kobo": paid_in_window},
        )
