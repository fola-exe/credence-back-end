from datetime import timedelta
from types import SimpleNamespace

import pytest

import app.modules.payments.receipts as receipts
from app.core.errors import UnsupportedFormat
from app.core.time import now_utc, today_wat
from app.models import Business, CreditTransaction, Debtor
from app.modules.transactions.balance import Balance


class _Db:
    def __init__(self, objects):
        self._objects = objects

    def get(self, model, ident):
        return self._objects.get(model, {}).get(ident)


def _db(monkeypatch, outstanding_kobo):
    today = today_wat()
    transaction = SimpleNamespace(
        id="tx-1",
        business_id="business-1",
        debtor_id="debtor-1",
        reference="CRD-123",
        invoice_number="INV-1",
        description="Goods",
        amount_kobo=1_500_000,
        due_date=today + timedelta(days=2),
        public_token="token-1",
    )
    payment = SimpleNamespace(
        transaction_id="tx-1",
        amount_kobo=500_000,
        paid_at=now_utc(),
        created_at=now_utc(),
        provider_mode="sandbox",
        receipt_number="RCT-000001",
        kora_reference="CRD-123-P1",
    )
    monkeypatch.setattr(
        receipts,
        "balance_for",
        lambda db, tx: Balance(
            1_500_000, 1_500_000 - outstanding_kobo, outstanding_kobo, 0, 100
        ),
    )
    db = _Db(
        {
            CreditTransaction: {"tx-1": transaction},
            Business: {"business-1": SimpleNamespace(name="Creditor")},
            Debtor: {"debtor-1": SimpleNamespace(name="Debtor")},
        }
    )
    return db, payment


def test_receipt_marked_settled(monkeypatch):
    db, payment = _db(monkeypatch, 0)

    body, content_type, filename = receipts.ReceiptService.render(db, payment)

    assert content_type == "text/html"
    assert filename is None
    assert "SETTLED" in body.decode("utf-8")
    assert "SANDBOX" in body.decode("utf-8")


def test_receipt_marked_partially_paid(monkeypatch):
    db, payment = _db(monkeypatch, 1_000_000)

    body, _, _ = receipts.ReceiptService.render(db, payment)

    assert "Partially paid" in body.decode("utf-8")
    assert "SETTLED" not in body.decode("utf-8")


def test_unsupported_receipt_format_is_rejected(monkeypatch):
    db, payment = _db(monkeypatch, 0)

    with pytest.raises(UnsupportedFormat):
        receipts.ReceiptService.render(db, payment, fmt="docx")
