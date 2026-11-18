from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.money import format_naira
from app.core.time import format_date_wat
from app.db.enums import EventActor
from app.models import TransactionEvent

EVENT_TYPES = (
    "transaction_created",
    "reminder_sent",
    "reminder_failed",
    "debtor_acknowledged",
    "promise_made",
    "promise_kept",
    "promise_missed",
    "payment_received",
    "payment_failed",
    "dispute_raised",
    "dispute_resolved",
    "note_added",
    "settled",
    "cancelled",
)


def record(
    db: Session,
    transaction_id: UUID,
    event_type: str,
    actor: EventActor,
    data: dict[str, Any] | None = None,
) -> TransactionEvent:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event type: {event_type}")
    event = TransactionEvent(
        transaction_id=transaction_id,
        type=event_type,
        actor=actor,
        data=data or {},
    )
    db.add(event)
    return event


def _date(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    return format_date_wat(value) if value is not None else ""


def _naira(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    return format_naira(int(value)) if value is not None else "₦0.00"


def render_text(event_type: str, data: dict[str, Any]) -> str:
    match event_type:
        case "transaction_created":
            return (
                f"Credit of {_naira(data, 'amount_kobo')} recorded "
                f"· due {_date(data, 'due_date')}"
            )
        case "reminder_sent":
            template = data.get("template", data.get("kind", "Reminder"))
            return f'"{template}" reminder emailed to {data.get("to", "")}'
        case "reminder_failed":
            return f"Reminder to {data.get('to', '')} failed"
        case "debtor_acknowledged":
            return f"{data.get('debtor_name', 'Debtor')} viewed and acknowledged the invoice"
        case "promise_made":
            message = data.get("message")
            suffix = f': "{message}"' if message else ""
            return (
                f"Promised to pay {_naira(data, 'promised_amount_kobo')} by "
                f"{_date(data, 'promised_date')}{suffix}"
            )
        case "promise_kept":
            return f"Promise for {_date(data, 'promised_date')} kept ✓"
        case "promise_missed":
            return f"Promise for {_date(data, 'promised_date')} missed ✗"
        case "payment_received":
            text = (
                f"Paid {_naira(data, 'amount_kobo')} via Kora "
                f"· receipt {data.get('receipt_number', '')} "
                f"· balance {_naira(data, 'balance_kobo')}"
            )
            if data.get("overpaid_kobo") or data.get("review_reason"):
                text += " · overpayment under review"
            return text
        case "payment_failed":
            return f"A payment attempt of {_naira(data, 'amount_kobo')} failed"
        case "dispute_raised":
            return f'Dispute: "{data.get("reason", "")}"'
        case "dispute_resolved":
            return f"Resolved by creditor: {data.get('note', '')}"
        case "note_added":
            return str(data.get("note", ""))
        case "settled":
            return "Fully settled · reminders stopped"
        case "cancelled":
            return "Cancelled · reminders stopped"
        case _:
            return "An update was recorded"


def timeline(db: Session, transaction_id: UUID) -> list[dict[str, Any]]:
    events = db.execute(
        select(TransactionEvent)
        .where(TransactionEvent.transaction_id == transaction_id)
        .order_by(TransactionEvent.created_at.desc())
    ).scalars().all()
    return [
        {
            "id": event.id,
            "type": event.type,
            "actor": event.actor.value,
            "data": event.data,
            "text": render_text(event.type, event.data),
            "created_at": event.created_at,
        }
        for event in events
    ]
