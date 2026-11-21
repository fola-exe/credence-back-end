import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, settings
from app.core.database import SessionLocal
from app.core.time import now_utc
from app.core.errors import InvalidWebhookBody, WebhookSignatureInvalid
from app.db.enums import CreditTransactionStatus, PaymentStatus
from app.integrations.kora.signature import canonical_data, sign
from app.models import (
    Business,
    BusinessCategory,
    CreditTransaction,
    Debtor,
    DebtorResponse,
    KoraWebhookEvent,
    Payment,
    Reminder,
    TransactionEvent,
)
from app.modules.payments import service as payment_service
from app.modules.payments.service import PaymentService


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setattr(
        payment_service.email_service,
        "send",
        lambda *args, **kwargs: SimpleNamespace(provider_message_id="test-message"),
    )
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        db.close()
        pytest.skip("integration database is unavailable")
    suffix = uuid4().hex[:12]
    reference = f"TST-{suffix}"
    business = Business(
        name=f"Test Business {suffix}",
        hashed_password="x",
        category=BusinessCategory.OTHER,
        address="Test address",
        phone=f"+2348{suffix}",
        email=f"business-{suffix}@example.test",
        registration_number=f"REG-{suffix[:6]}",
        credit_limit_kobo=1_000_000,
    )
    debtor = Debtor(
        business_id=business.id,
        name=f"Test Debtor {suffix}",
        email=f"debtor-{suffix}@example.test",
        phone="+2348012345678",
    )
    db.add(business)
    db.flush()
    debtor.business_id = business.id
    db.add(debtor)
    db.flush()
    transaction = CreditTransaction(
        business_id=business.id,
        debtor_id=debtor.id,
        created_by_business_id=business.id,
        reference=reference,
        description="Test credit",
        amount_kobo=150_000,
        issue_date=date.today(),
        due_date=date.today() + timedelta(days=7),
        public_token=uuid4().hex,
        status=CreditTransactionStatus.ACTIVE,
    )
    db.add(transaction)
    db.flush()
    payment = Payment(
        transaction_id=transaction.id,
        kora_reference=f"{reference}-P1",
        attempt_number=1,
        amount_kobo=150_000,
        status=PaymentStatus.INITIATED,
        provider_mode="sandbox",
    )
    db.add(payment)
    db.commit()
    try:
        yield SimpleNamespace(
            db=db,
            reference=reference,
            business=business,
            debtor=debtor,
            transaction=transaction,
            payment=payment,
        )
    finally:
        db.execute(
            delete(KoraWebhookEvent).where(
                KoraWebhookEvent.kora_reference.like(f"{reference}%")
            )
        )
        db.execute(
            delete(TransactionEvent).where(
                TransactionEvent.transaction_id == transaction.id
            )
        )
        db.execute(
            delete(DebtorResponse).where(DebtorResponse.transaction_id == transaction.id)
        )
        db.execute(
            delete(Reminder).where(Reminder.transaction_id == transaction.id)
        )
        db.execute(delete(Payment).where(Payment.transaction_id == transaction.id))
        db.execute(
            delete(CreditTransaction).where(CreditTransaction.id == transaction.id)
        )
        db.execute(delete(Debtor).where(Debtor.id == debtor.id))
        db.execute(delete(Business).where(Business.id == business.id))
        db.commit()
        db.close()


def _signed_webhook(reference: str, *, event: str = "charge.success", amount: str = "1500.00"):
    payload = {
        "event": event,
        "data": {
            "reference": reference,
            "status": "success" if event == "charge.success" else "failed",
            "amount": amount,
            "currency": "NGN",
        },
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return raw, sign(canonical_data(raw), settings.kora_signing_secret)


def _webhook_row(db, reference: str):
    return db.execute(
        select(KoraWebhookEvent).where(KoraWebhookEvent.kora_reference == reference)
    ).scalars().first()


def test_unknown_reference_is_recorded_without_money_changes(ctx):
    unknown = f"UNKNOWN-{ctx.reference}"
    raw, signature = _signed_webhook(unknown)

    outcome = PaymentService.process_webhook(ctx.db, raw, signature)

    row = _webhook_row(ctx.db, unknown)
    assert outcome == "unknown_reference"
    assert row is not None and row.outcome == "unknown_reference"
    assert ctx.payment.status == PaymentStatus.INITIATED


def test_bad_signature_is_recorded_and_rejected(ctx):
    raw, _ = _signed_webhook(ctx.payment.kora_reference)

    with pytest.raises(WebhookSignatureInvalid):
        PaymentService.process_webhook(ctx.db, raw, "bad-signature")

    row = _webhook_row(ctx.db, ctx.payment.kora_reference)
    assert row is not None and row.signature_ok is False
    assert row.outcome == "rejected"
    assert ctx.payment.status == PaymentStatus.INITIATED


def test_duplicate_webhook_is_a_noop(ctx):
    first = PaymentService.process_demo_charge(
        ctx.db, ctx.payment.kora_reference, "success"
    )
    second = PaymentService.process_demo_charge(
        ctx.db, ctx.payment.kora_reference, "success"
    )

    assert first == "applied:raw"
    assert second == "duplicate"

    rows = ctx.db.execute(
        select(KoraWebhookEvent).where(
            KoraWebhookEvent.kora_reference == ctx.payment.kora_reference
        )
    ).scalars().all()
    assert len(rows) == 1
    assert ctx.payment.status == PaymentStatus.SUCCESSFUL


def test_malformed_webhook_is_rejected(ctx):
    with pytest.raises(InvalidWebhookBody):
        PaymentService.process_webhook(ctx.db, b'{"event":"charge.success"}', "sig")


def test_demo_success_applies_gross_amount_and_settles(ctx):
    outcome = PaymentService.process_demo_charge(
        ctx.db, ctx.payment.kora_reference, "success"
    )

    ctx.db.refresh(ctx.payment)
    ctx.db.refresh(ctx.transaction)
    events = ctx.db.execute(
        select(TransactionEvent).where(
            TransactionEvent.transaction_id == ctx.transaction.id
        )
    ).scalars().all()
    types = {event.type for event in events}

    assert outcome == "applied:raw"
    assert ctx.payment.status == PaymentStatus.SUCCESSFUL
    assert ctx.payment.amount_kobo == 150_000
    assert ctx.payment.receipt_number is not None
    assert ctx.transaction.status == CreditTransactionStatus.SETTLED
    assert ctx.transaction.settled_at is not None
    assert {"payment_received", "settled"} <= types


def test_demo_failed_charge_marks_payment_failed(ctx):
    outcome = PaymentService.process_demo_charge(
        ctx.db, ctx.payment.kora_reference, "failed"
    )

    ctx.db.refresh(ctx.payment)
    assert outcome == "applied"
    assert ctx.payment.status == PaymentStatus.FAILED
    assert ctx.payment.failure_reason == "provider_declined"


def test_overpayment_is_recorded_and_flagged(ctx):
    paid_at = PaymentService.apply_verified_charge(
        ctx.db, ctx.payment.id, 160_000, datetime.now(timezone.utc), {"demo": True}
    )

    ctx.db.refresh(ctx.payment)
    ctx.db.refresh(ctx.transaction)
    assert paid_at == "settled"
    assert ctx.payment.overpaid_kobo == 10_000
    assert ctx.payment.review_reason == "overpaid"
    assert ctx.transaction.status == CreditTransactionStatus.SETTLED


def test_reconciliation_counts_still_pending_attempt(ctx):
    ctx.db.execute(
        update(Payment)
        .where(Payment.id == ctx.payment.id)
        .values(created_at=now_utc() - timedelta(minutes=30))
    )
    ctx.db.commit()
    config = Settings(
        _env_file=None,
        DATABASE_URL="postgresql+psycopg://u:p@localhost:5432/db",
        JWT_SECRET_KEY="test-secret",
        KORA_SECRET_KEY="",
        KORA_MODE="sandbox",
    )

    results = PaymentService.reconcile_stale_payments(
        ctx.db, config=config, references={ctx.payment.kora_reference}
    )

    ctx.db.refresh(ctx.payment)
    assert results == [(ctx.payment.kora_reference, "pending")]
    assert ctx.payment.status == PaymentStatus.INITIATED
    assert ctx.payment.attempt_count == 1


def test_verified_payment_on_cancelled_transaction_keeps_status(ctx):
    ctx.transaction.status = CreditTransactionStatus.CANCELLED
    ctx.db.commit()

    PaymentService.apply_verified_charge(
        ctx.db, ctx.payment.id, 150_000, datetime.now(timezone.utc), {"demo": True}
    )

    ctx.db.refresh(ctx.payment)
    ctx.db.refresh(ctx.transaction)
    assert ctx.payment.status == PaymentStatus.SUCCESSFUL
    assert ctx.payment.review_reason == "paid_cancelled_transaction"
    assert ctx.transaction.status == CreditTransactionStatus.CANCELLED
