from datetime import date

from app.db.enums import CreditTransactionStatus
from app.modules.reminders.templates import choose_template


def test_pending_ack_chooses_new_credit():
    status = CreditTransactionStatus.PENDING_ACK

    assert (
        choose_template(status, date(2026, 11, 20), date(2026, 11, 18))
        == "new_credit"
    )


def test_upcoming_due_today_and_overdue_templates():
    status = CreditTransactionStatus.ACTIVE

    assert (
        choose_template(status, date(2026, 11, 20), date(2026, 11, 18))
        == "upcoming"
    )
    assert (
        choose_template(status, date(2026, 11, 18), date(2026, 11, 18))
        == "due_today"
    )
    assert (
        choose_template(status, date(2026, 11, 15), date(2026, 11, 18))
        == "overdue_1"
    )
    assert (
        choose_template(status, date(2026, 11, 10), date(2026, 11, 18))
        == "overdue_followup"
    )
