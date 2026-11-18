from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import now_utc
from app.db.enums import EventActor, ReminderKind, ReminderStatus
from app.integrations.email.client import EmailError, build_context, email_service
from app.models import Reminder
from app.modules.reminders.schedule import build_schedule
from app.modules.transactions.events import record


class ReminderService:
    @staticmethod
    def create_for_transaction(
        db: Session, transaction, now: datetime | None = None
    ) -> list[Reminder]:
        current = now or now_utc()
        reminders = [
            Reminder(
                transaction_id=transaction.id,
                kind=ReminderKind.NEW_CREDIT,
                channel="email",
                scheduled_for=current,
                status=ReminderStatus.SCHEDULED,
            )
        ]
        for plan in build_schedule(
            transaction.issue_date, transaction.due_date, current
        ):
            reminders.append(
                Reminder(
                    transaction_id=transaction.id,
                    kind=plan.kind,
                    channel="email",
                    scheduled_for=plan.scheduled_for,
                    status=ReminderStatus.SCHEDULED,
                )
            )
        db.add_all(reminders)
        return reminders

    @staticmethod
    def next_scheduled(db: Session, transaction_id) -> Reminder | None:
        return db.execute(
            select(Reminder)
            .where(
                Reminder.transaction_id == transaction_id,
                Reminder.status == ReminderStatus.SCHEDULED,
            )
            .order_by(Reminder.scheduled_for)
        ).scalars().first()

    @staticmethod
    def deliver_new_credit(
        db: Session,
        reminder: Reminder,
        transaction,
        balance,
        debtor,
        business,
    ) -> None:
        context = build_context(transaction, balance, debtor, business)
        template = "new_credit"
        try:
            result = email_service.send("new_credit", to=debtor.email, context=context)
        except EmailError as exc:
            reminder.status = ReminderStatus.FAILED
            reminder.error = str(exc)[:500]
            reminder.attempt_count += 1
            record(
                db,
                transaction.id,
                "reminder_failed",
                EventActor.SYSTEM,
                {"kind": reminder.kind.value, "to": debtor.email, "error": str(exc)},
            )
        else:
            reminder.status = ReminderStatus.SENT
            reminder.sent_at = now_utc()
            reminder.provider_message_id = result.provider_message_id
            record(
                db,
                transaction.id,
                "reminder_sent",
                EventActor.SYSTEM,
                {
                    "kind": reminder.kind.value,
                    "template": template,
                    "to": debtor.email,
                    "provider_message_id": result.provider_message_id,
                },
            )
        db.commit()
