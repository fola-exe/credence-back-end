from datetime import timedelta
from types import SimpleNamespace

import app.modules.payments.service as service
from app.core.time import today_wat
from app.models import Business, CreditTransaction, Debtor
from app.modules.transactions.balance import Balance


class _Db:
    def __init__(self, objects):
        self._objects = objects

    def get(self, model, ident):
        return self._objects.get(model, {}).get(ident)


def _objects():
    transaction = SimpleNamespace(
        id="tx-1",
        business_id="business-1",
        debtor_id="debtor-1",
        reference="CRD-123",
        invoice_number="INV-1",
        description="Goods",
        amount_kobo=1_500_000,
        due_date=today_wat() + timedelta(days=2),
        public_token="token-1",
    )
    business = SimpleNamespace(name="Creditor", email="creditor@example.test")
    debtor = SimpleNamespace(name="Debtor", email="debtor@example.test")
    payment = SimpleNamespace(
        amount_kobo=500_000,
        receipt_number="RCT-000001",
        kora_reference="CRD-123-P1",
    )
    db = _Db(
        {
            Business: {"business-1": business},
            Debtor: {"debtor-1": debtor},
            CreditTransaction: {"tx-1": transaction},
        }
    )
    return db, transaction, payment, business, debtor


def test_non_settlement_payment_email_ccs_creditor(monkeypatch):
    db, transaction, payment, business, debtor = _objects()
    monkeypatch.setattr(
        service,
        "balance_for",
        lambda db, tx: Balance(1_500_000, 500_000, 1_000_000, 0, 33),
    )
    sent = []
    monkeypatch.setattr(
        service.email_service,
        "send",
        lambda template, **kw: sent.append((template, kw)),
    )

    service._notify_payment(db, payment, transaction, False)

    assert len(sent) == 1
    template, kwargs = sent[0]
    assert template == "payment_receipt"
    assert kwargs["to"] == debtor.email
    assert kwargs["cc"] == business.email
    assert kwargs["context"]["receipt_number"] == "RCT-000001"


def test_settlement_email_is_exclusive(monkeypatch):
    db, transaction, payment, _, debtor = _objects()
    monkeypatch.setattr(
        service,
        "balance_for",
        lambda db, tx: Balance(1_500_000, 1_500_000, 0, 0, 100),
    )
    sent = []
    monkeypatch.setattr(
        service.email_service,
        "send",
        lambda template, **kw: sent.append((template, kw)),
    )

    service._notify_payment(db, payment, transaction, True)

    assert len(sent) == 1
    assert sent[0][0] == "settled"
    assert sent[0][1]["to"] == debtor.email
    assert sent[0][1]["cc"] is None
