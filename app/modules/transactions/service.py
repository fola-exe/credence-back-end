import secrets
from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import InvalidDateRange, ValidationFailed
from app.core.time import now_utc, today_wat
from app.db.enums import CreditTransactionStatus, EventActor, ReminderKind
from app.models import Business, CreditTransaction
from app.modules.capacity.service import CreditCapacityService
from app.modules.debtors.service import DebtorService
from app.modules.reminders.service import ReminderService
from app.modules.transactions.balance import balance_for, display_status
from app.modules.transactions.events import record
from app.modules.transactions.schemas import CreateTransactionSchema


class CreditTransactionService:
    @staticmethod
    def _reference(db: Session) -> str:
        value = db.execute(
            text("SELECT nextval('credit_transaction_reference_seq')")
        ).scalar_one()
        return f"CRD-{int(value):06d}"

    @classmethod
    def create(
        cls, db: Session, business: Business, payload: CreateTransactionSchema
    ) -> dict:
        today = today_wat()
        if payload.due_date < payload.issue_date:
            raise InvalidDateRange()
        if payload.issue_date > today:
            raise ValidationFailed(
                "The request is invalid.",
                fields={"issue_date": "Issue date cannot be in the future."},
            )
        if payload.issue_date < today - timedelta(days=365):
            raise ValidationFailed(
                "The request is invalid.",
                fields={"issue_date": "Issue date is too far in the past."},
            )

        try:
            locked = db.execute(
                select(Business).where(Business.id == business.id).with_for_update()
            ).scalar_one()

            debtor = DebtorService.resolve_or_create(
                db, business.id, payload.debtor_id, payload.new_debtor
            )
            db.flush()

            CreditCapacityService.assert_within_limit(
                db,
                locked,
                payload.amount_kobo,
                override=payload.override,
                override_reason=payload.override_reason,
                debtor_id=debtor.id,
            )

            transaction = CreditTransaction(
                business_id=locked.id,
                debtor_id=debtor.id,
                reference=cls._reference(db),
                invoice_number=payload.invoice_number,
                description=payload.description.strip(),
                amount_kobo=payload.amount_kobo,
                issue_date=payload.issue_date,
                due_date=payload.due_date,
                notes=payload.notes,
                status=CreditTransactionStatus.PENDING_ACK,
                public_token=secrets.token_urlsafe(32),
                capacity_override=payload.override,
                override_reason=payload.override_reason,
                created_by_business_id=locked.id,
            )
            db.add(transaction)
            db.flush()

            reminders = ReminderService.create_for_transaction(
                db, transaction, now=now_utc()
            )
            record(
                db,
                transaction.id,
                "transaction_created",
                EventActor.CREDITOR,
                {
                    "amount_kobo": transaction.amount_kobo,
                    "due_date": transaction.due_date.isoformat(),
                    "debtor_name": debtor.name,
                    "reference": transaction.reference,
                },
            )
            db.commit()
        except Exception:
            db.rollback()
            raise

        db.refresh(transaction)
        for reminder in reminders:
            db.refresh(reminder)

        balance = balance_for(db, transaction)
        new_credit = next(
            reminder
            for reminder in reminders
            if reminder.kind == ReminderKind.NEW_CREDIT
        )
        ReminderService.deliver_new_credit(
            db, new_credit, transaction, balance, debtor, locked
        )
        db.refresh(new_credit)
        next_reminder = ReminderService.next_scheduled(db, transaction.id)

        return {
            "transaction": {
                "id": transaction.id,
                "reference": transaction.reference,
                "invoice_number": transaction.invoice_number,
                "description": transaction.description,
                "amount_kobo": transaction.amount_kobo,
                "paid_kobo": balance.paid_kobo,
                "outstanding_kobo": balance.outstanding_kobo,
                "overpaid_kobo": balance.overpaid_kobo,
                "status": transaction.status.value,
                "display_status": display_status(transaction, balance.outstanding_kobo, today).value,
                "days_overdue": 0,
                "issue_date": transaction.issue_date,
                "due_date": transaction.due_date,
                "notes": transaction.notes,
                "debtor": {
                    "id": debtor.id,
                    "name": debtor.name,
                    "email": debtor.email,
                    "phone": debtor.phone,
                },
                "has_open_promise": False,
                "has_open_dispute": False,
                "next_reminder": (
                    next_reminder.scheduled_for if next_reminder else None
                ),
                "created_at": transaction.created_at,
            },
            "pay_link": f"{settings.app_url}/pay/{transaction.public_token}",
            "reminders": [
                {
                    "id": reminder.id,
                    "kind": reminder.kind.value,
                    "channel": reminder.channel,
                    "scheduled_for": reminder.scheduled_for,
                    "status": reminder.status.value,
                    "sent_at": reminder.sent_at,
                    "skip_reason": reminder.skip_reason,
                    "error": reminder.error,
                }
                for reminder in reminders
            ],
        }
