import json
from datetime import timedelta
from types import SimpleNamespace

import app.modules.public.projection as projection
from app.core.time import today_wat
from app.db.enums import CreditTransactionStatus
from app.models import Business, Debtor
from app.modules.transactions.balance import Balance


class _Result:
    def __init__(self, first=None, rows=None):
        self._first = first
        self._rows = rows or []

    def scalars(self):
        return self

    def first(self):
        return self._first

    def all(self):
        return self._rows


class _Db:
    def __init__(self, objects, first=None, rows=None):
        self._first = first
        self._rows = rows or []
        self._objects = objects

    def get(self, model, ident):
        return self._objects.get(model, {}).get(ident)

    def execute(self, statement):
        return _Result(self._first, self._rows)


def _objects():
    today = today_wat()
    transaction = SimpleNamespace(
        id="tx-1",
        reference="CRD-123",
        invoice_number="INV-1",
        description="Goods",
        amount_kobo=1_500_000,
        issue_date=today - timedelta(days=10),
        due_date=today + timedelta(days=5),
        status=CreditTransactionStatus.ACTIVE,
        public_token="token-1",
        business_id="business-1",
        debtor_id="debtor-1",
        notes="internal",
        override_reason="secret",
    )
    business = SimpleNamespace(
        name="Adeyemi Wholesale Ltd",
        email="business@example.test",
        logo_url=None,
    )
    debtor = SimpleNamespace(name="Bola Ade", email="debtor@example.test")
    return transaction, business, debtor


def test_initials_and_receipt_url():
    assert projection.initials("Adeyemi Wholesale Ltd") == "AW"
    assert projection.initials("") == "?"
    assert projection.receipt_url("tok", "RCT-000001") == (
        "/public/tx/tok/receipts/RCT-000001"
    )


def test_public_transaction_exposes_only_safe_fields(monkeypatch):
    transaction, business, debtor = _objects()
    monkeypatch.setattr(
        projection,
        "balance_for",
        lambda db, tx: Balance(1_500_000, 1_000_000, 500_000, 0, 67),
    )
    db = _Db(
        {
            Business: {"business-1": business},
            Debtor: {"debtor-1": debtor},
        }
    )

    result = projection.public_transaction(db, transaction)

    assert set(result) == {
        "creditor",
        "transaction",
        "open_promise",
        "open_dispute",
        "payments",
        "payment_config",
    }
    assert result["creditor"]["initials"] == "AW"
    assert result["transaction"]["outstanding_kobo"] == 500_000
    assert result["transaction"]["actions"]["can_pay"] is True
    assert result["payment_config"]["currency"] == "NGN"

    text = json.dumps(result, default=str)
    assert "internal" not in text
    assert "secret" not in text
    assert "raw_webhook" not in text
    assert "capacity_override" not in text
