from datetime import date
from types import SimpleNamespace

import pytest

from app.db.enums import EventActor
from app.modules.transactions import events


def test_event_types_complete():
    assert len(events.EVENT_TYPES) == 14
    assert "transaction_created" in events.EVENT_TYPES
    assert "cancelled" in events.EVENT_TYPES


def test_render_text_transaction_created():
    text = events.render_text(
        "transaction_created",
        {"amount_kobo": 100_000, "due_date": date(2026, 11, 18)},
    )

    assert text == "Credit of ₦1,000.00 recorded · due Wed 18 Nov 2026"


def test_render_text_reminder_sent_uses_template():
    text = events.render_text(
        "reminder_sent", {"template": "new_credit", "to": "a@b.com"}
    )

    assert text == '"new_credit" reminder emailed to a@b.com'


def test_render_text_payment_received_flags_overpayment():
    text = events.render_text(
        "payment_received",
        {
            "amount_kobo": 120_000,
            "receipt_number": "RCT-1",
            "balance_kobo": 0,
            "overpaid_kobo": 20_000,
        },
    )

    assert text.endswith("· overpayment under review")


def test_record_rejects_unknown_type():
    db = SimpleNamespace(add=lambda event: None)

    with pytest.raises(ValueError, match="unknown event type"):
        events.record(db, "id", "nope", EventActor.SYSTEM)


def test_record_appends_event():
    added = []
    db = SimpleNamespace(add=added.append)

    event = events.record(
        db,
        "id",
        "transaction_created",
        EventActor.CREDITOR,
        {"amount_kobo": 1},
    )

    assert added == [event]
    assert event.type == "transaction_created"
