from types import SimpleNamespace

from app.modules.payments.service import PaymentService, _parse_datetime


def test_parse_datetime_normalizes_iso_strings():
    aware = _parse_datetime("2026-01-02T03:04:05Z")
    naive = _parse_datetime("2026-01-02T03:04:05")

    assert aware.tzinfo is not None
    assert naive.tzinfo is not None
    assert aware.utcoffset().total_seconds() == 0
    assert naive.utcoffset().total_seconds() == 0


def test_process_verification_rejects_wrong_amount(monkeypatch):
    reasons = []

    def fake_mark_failed(db, payment, reason, raw=None):
        reasons.append(reason)
        return reason

    monkeypatch.setattr(
        PaymentService, "mark_failed", staticmethod(fake_mark_failed)
    )
    payment = SimpleNamespace(id="p1", amount_kobo=150_000)
    verification = {
        "data": {"status": "success", "currency": "NGN", "amount": "1400.00"}
    }

    outcome = PaymentService._process_verification(None, payment, verification, {})

    assert outcome == reasons[0] == "amount_mismatch"


def test_process_verification_reports_signature_strategy(monkeypatch):
    applied = []
    monkeypatch.setattr(
        PaymentService,
        "apply_verified_charge",
        staticmethod(
            lambda db, payment_id, amount, paid_at, raw: applied.append(payment_id)
            or "applied"
        ),
    )
    payment = SimpleNamespace(id="p1", amount_kobo=150_000)
    verification = {
        "data": {
            "status": "success",
            "currency": "NGN",
            "amount": "1500.00",
            "paid_at": "2026-01-02T03:04:05Z",
        }
    }

    outcome = PaymentService._process_verification(
        None, payment, verification, {}, strategy="canonical"
    )

    assert outcome == "applied:canon"
    assert applied == ["p1"]


def test_process_verification_marks_provider_non_success(monkeypatch):
    reasons = []

    def fake_mark_failed(db, payment, reason, raw=None):
        reasons.append(reason)
        return reason

    monkeypatch.setattr(
        PaymentService, "mark_failed", staticmethod(fake_mark_failed)
    )
    payment = SimpleNamespace(id="p1", amount_kobo=150_000)

    outcome = PaymentService._process_verification(
        None, payment, {"data": {"status": "failed"}}, {}
    )

    assert outcome == reasons[0] == "provider_non_success"
