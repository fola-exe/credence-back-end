from datetime import date
from types import SimpleNamespace

from app.db.enums import CreditTransactionStatus, DisplayStatus
from app.modules.transactions.balance import calculate_balance, display_status


def _tx(status, due):
    return SimpleNamespace(status=status, due_date=due)


def test_calculate_balance_partial():
    balance = calculate_balance(100_000, 30_000)

    assert balance.amount_kobo == 100_000
    assert balance.paid_kobo == 30_000
    assert balance.outstanding_kobo == 70_000
    assert balance.overpaid_kobo == 0
    assert balance.progress_pct == 30


def test_calculate_balance_overpaid_is_clamped():
    balance = calculate_balance(100_000, 125_000)

    assert balance.outstanding_kobo == 0
    assert balance.overpaid_kobo == 25_000
    assert balance.progress_pct == 100


def test_display_status_overdue_when_unpaid_and_past_due():
    tx = _tx(CreditTransactionStatus.PENDING_ACK, date(2026, 11, 20))

    assert display_status(tx, 1, date(2026, 11, 25)) == DisplayStatus.OVERDUE


def test_display_status_pending_ack_maps_to_pending():
    tx = _tx(CreditTransactionStatus.PENDING_ACK, date(2026, 11, 20))

    assert display_status(tx, 1, date(2026, 11, 18)) == DisplayStatus.PENDING


def test_display_status_cancelled_wins_over_overdue():
    tx = _tx(CreditTransactionStatus.CANCELLED, date(2026, 11, 20))

    assert display_status(tx, 1, date(2026, 11, 25)) == DisplayStatus.CANCELLED


def test_display_status_no_overdue_when_balance_zero():
    tx = _tx(CreditTransactionStatus.PENDING_ACK, date(2026, 11, 20))

    assert display_status(tx, 0, date(2026, 11, 25)) == DisplayStatus.PENDING
