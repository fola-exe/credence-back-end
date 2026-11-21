import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.core.errors import (
    DemoModeDisabled,
    InvalidWebhookBody,
    PaymentNotFound,
    WebhookSignatureInvalid,
    WebhookVerificationFailed,
)
from app.core.logging import log_event
from app.core.money import format_naira, naira_to_kobo
from app.core.time import now_utc
from app.db.enums import (
    CreditTransactionStatus,
    EventActor,
    PaymentStatus,
    ReminderStatus,
)
from app.integrations.email.client import EmailError, build_context, email_service
from app.integrations.kora.client import get_kora_provider
from app.integrations.kora.provider import DemoKoraProvider, KoraProviderError
from app.integrations.kora.signature import matching_strategy
from app.models import (
    Business,
    CreditTransaction,
    Debtor,
    KoraWebhookEvent,
    Payment,
    Reminder,
)
from app.modules.promises.service import PromiseService
from app.modules.transactions.balance import balance_for
from app.modules.transactions.events import record

HANDLED_EVENTS = {"charge.success", "charge.failed"}


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return now_utc()


def _successful_payments(db: Session, transaction_id: UUID) -> list[Payment]:
    return list(
        db.execute(
            select(Payment).where(
                Payment.transaction_id == transaction_id,
                Payment.status == PaymentStatus.SUCCESSFUL,
            ).order_by(Payment.paid_at)
        ).scalars().all()
    )


def _insert_webhook_row(
    db: Session,
    reference: str,
    event: str,
    payload: dict,
    signature_ok: bool,
    outcome: str | None,
) -> bool:
    statement = (
        insert(KoraWebhookEvent)
        .values(
            kora_reference=reference,
            event=event,
            signature_ok=signature_ok,
            payload=payload,
            outcome=outcome,
        )
        .on_conflict_do_nothing(index_elements=["kora_reference", "event"])
        .returning(KoraWebhookEvent.id)
    )
    inserted = db.execute(statement).scalar_one_or_none() is not None
    db.commit()
    return inserted


def _set_webhook_outcome(db: Session, reference: str, event: str, outcome: str) -> None:
    db.execute(
        KoraWebhookEvent.__table__.update()
        .where(
            KoraWebhookEvent.kora_reference == reference,
            KoraWebhookEvent.event == event,
        )
        .values(outcome=outcome, processed_at=now_utc())
    )
    db.commit()


def _receipt_number(db: Session) -> str:
    value = db.execute(text("SELECT nextval('payment_receipt_seq')")).scalar_one()
    return f"RCT-{int(value):06d}"


def _notify_payment(db: Session, payment: Payment, transaction: CreditTransaction, settled_now: bool) -> None:
    business = db.get(Business, transaction.business_id)
    debtor = db.get(Debtor, transaction.debtor_id)
    balance = balance_for(db, transaction)
    link = (
        f"{settings.user_facing_url}/public/tx/{transaction.public_token}"
        f"/receipts/{payment.receipt_number}"
    )
    context = build_context(transaction, balance, debtor, business)
    context.update(
        {
            "amount_paid": format_naira(payment.amount_kobo),
            "receipt_number": payment.receipt_number,
            "receipt_link": link,
        }
    )
    template = "settled" if settled_now else "payment_receipt"
    try:
        email_service.send(
            template,
            to=debtor.email,
            context=context,
            cc=None if settled_now else business.email,
        )
    except EmailError as exc:
        log_event(
            "email_failed",
            template=template,
            reference=transaction.reference,
            error=str(exc),
        )
        record(
            db,
            transaction.id,
            "reminder_failed",
            EventActor.SYSTEM,
            {"template": template, "to": debtor.email, "error": str(exc)},
        )
        db.commit()


class PaymentService:
    @staticmethod
    def mark_failed(
        db: Session,
        payment: Payment,
        reason: str,
        raw_payload: dict | None = None,
    ) -> str:
        fresh = db.execute(
            select(Payment).where(Payment.id == payment.id).with_for_update()
        ).scalars().one()
        if fresh.status == PaymentStatus.SUCCESSFUL:
            return "already_applied"
        fresh.status = PaymentStatus.FAILED
        fresh.failure_reason = reason
        if raw_payload is not None:
            fresh.raw_webhook = raw_payload
        record(
            db,
            fresh.transaction_id,
            "payment_failed",
            EventActor.SYSTEM,
            {"amount_kobo": fresh.amount_kobo, "reason": reason},
        )
        db.commit()
        return "failed"

    @staticmethod
    def apply_verified_charge(
        db: Session,
        payment_id: UUID,
        verified_amount_kobo: int,
        paid_at: datetime,
        raw_payload: dict,
    ) -> str:
        payment = db.execute(
            select(Payment).where(Payment.id == payment_id).with_for_update()
        ).scalars().one()
        if payment.status == PaymentStatus.SUCCESSFUL:
            return "already_applied"
        transaction = db.execute(
            select(CreditTransaction)
            .where(CreditTransaction.id == payment.transaction_id)
            .with_for_update()
        ).scalars().one()

        paid_others = int(
            db.execute(
                select(func.coalesce(func.sum(Payment.amount_kobo), 0)).where(
                    Payment.transaction_id == transaction.id,
                    Payment.status == PaymentStatus.SUCCESSFUL,
                    Payment.id != payment.id,
                )
            ).scalar_one()
            or 0
        )
        balance_before = max(transaction.amount_kobo - paid_others, 0)
        credited = verified_amount_kobo
        status_before = transaction.status

        if status_before == CreditTransactionStatus.CANCELLED:
            overpaid = None
            review = "paid_cancelled_transaction"
        else:
            excess = max(credited - balance_before, 0)
            overpaid = excess or None
            review = "overpaid" if excess else None

        payment.status = PaymentStatus.SUCCESSFUL
        payment.paid_at = paid_at
        payment.verified_at = now_utc()
        payment.receipt_number = _receipt_number(db)
        payment.raw_webhook = raw_payload
        payment.overpaid_kobo = overpaid
        payment.review_reason = review

        balance_after = max(balance_before - credited, 0)
        if status_before != CreditTransactionStatus.CANCELLED:
            if balance_after == 0:
                transaction.status = CreditTransactionStatus.SETTLED
                transaction.settled_at = transaction.settled_at or now_utc()
            elif status_before in (
                CreditTransactionStatus.PENDING_ACK,
                CreditTransactionStatus.ACTIVE,
                CreditTransactionStatus.PARTIALLY_PAID,
            ):
                transaction.status = CreditTransactionStatus.PARTIALLY_PAID
        settled_now = (
            transaction.status == CreditTransactionStatus.SETTLED
            and status_before != CreditTransactionStatus.SETTLED
        )

        event_data: dict[str, Any] = {
            "amount_kobo": credited,
            "receipt_number": payment.receipt_number,
            "balance_kobo": balance_after,
            "kora_reference": payment.kora_reference,
            "paid_at": paid_at.isoformat(),
            "provider_mode": payment.provider_mode,
        }
        if overpaid is not None:
            event_data["overpaid_kobo"] = overpaid
        if review is not None:
            event_data["review_reason"] = review
        record(db, transaction.id, "payment_received", EventActor.DEBTOR, event_data)

        if settled_now:
            record(db, transaction.id, "settled", EventActor.SYSTEM, {})
            for reminder in db.scalars(
                select(Reminder).where(
                    Reminder.transaction_id == transaction.id,
                    Reminder.status == ReminderStatus.SCHEDULED,
                )
            ).all():
                reminder.status = ReminderStatus.CANCELLED
                reminder.skip_reason = "settled"

        PromiseService.check_after_payment(
            db, transaction, _successful_payments(db, transaction.id), paid_at
        )
        db.commit()
        db.refresh(payment)
        db.refresh(transaction)
        _notify_payment(db, payment, transaction, settled_now)
        return "settled" if settled_now else "applied"

    @classmethod
    def _process_verification(
        cls,
        db: Session,
        payment: Payment,
        verification: dict[str, Any],
        raw_payload: dict[str, Any],
        *,
        strategy: str | None = None,
    ) -> str:
        data = verification.get("data") or {}
        if data.get("status") != "success":
            return cls.mark_failed(db, payment, "provider_non_success", raw_payload)
        if data.get("currency") != "NGN":
            return cls.mark_failed(db, payment, "currency_mismatch", raw_payload)
        try:
            actual_kobo = naira_to_kobo(data["amount"])
        except (KeyError, ValueError, ArithmeticError):
            return cls.mark_failed(db, payment, "amount_mismatch", raw_payload)
        if actual_kobo != payment.amount_kobo:
            reason = "amount_over_mismatch" if actual_kobo > payment.amount_kobo else "amount_mismatch"
            return cls.mark_failed(db, payment, reason, raw_payload)
        paid_at = _parse_datetime(data.get("paid_at") or data.get("transaction_date"))
        result = cls.apply_verified_charge(db, payment.id, actual_kobo, paid_at, raw_payload)
        if result == "already_applied":
            return "duplicate"
        if strategy == "raw":
            return "applied:raw"
        if strategy == "canonical":
            return "applied:canon"
        return "applied"

    @classmethod
    def process_webhook(
        cls,
        db: Session,
        raw: bytes,
        signature_header: str | None,
        *,
        config: Settings | None = None,
    ) -> str:
        current = config or settings
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise InvalidWebhookBody() from exc
        if not isinstance(payload, dict):
            raise InvalidWebhookBody()

        event = str(payload.get("event") or "")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise InvalidWebhookBody()
        reference = str(data.get("reference") or "")

        strategy = matching_strategy(
            raw,
            signature_header,
            current.kora_signing_secret,
            current.kora_signature_strategy,
        )
        if strategy is None:
            _insert_webhook_row(
                db,
                reference or "",
                event or "signature_invalid",
                payload,
                False,
                "rejected",
            )
            raise WebhookSignatureInvalid()

        if not reference:
            _insert_webhook_row(db, "", event, payload, True, "ignored")
            return "ignored"
        if not _insert_webhook_row(db, reference, event, payload, True, None):
            return "duplicate"

        payment = db.execute(
            select(Payment).where(Payment.kora_reference == reference)
        ).scalars().first()
        if payment is None:
            _set_webhook_outcome(db, reference, event, "unknown_reference")
            return "unknown_reference"
        if payment.status == PaymentStatus.SUCCESSFUL:
            _set_webhook_outcome(db, reference, event, "duplicate")
            return "duplicate"
        if event not in HANDLED_EVENTS:
            _set_webhook_outcome(db, reference, event, "ignored")
            return "ignored"
        if event == "charge.failed":
            cls.mark_failed(db, payment, "provider_declined", data)
            _set_webhook_outcome(db, reference, event, "applied")
            return "applied"

        try:
            verification = get_kora_provider(current).verify(reference, payment=payment)
        except KoraProviderError as exc:
            _set_webhook_outcome(db, reference, event, "error:verify_failed")
            log_event("kora_verify_failed", reference=reference, error=str(exc))
            raise WebhookVerificationFailed() from exc
        outcome = cls._process_verification(
            db, payment, verification, data, strategy=strategy
        )
        _set_webhook_outcome(db, reference, event, outcome)
        return outcome

    @classmethod
    def process_demo_charge(cls, db: Session, reference: str, outcome: str) -> str:
        if not settings.kora_demo_enabled:
            raise DemoModeDisabled()
        payment = db.execute(
            select(Payment).where(Payment.kora_reference == reference)
        ).scalars().first()
        if payment is None:
            raise PaymentNotFound()
        raw, signature = DemoKoraProvider(settings).make_webhook(
            reference, payment.amount_kobo, outcome
        )
        payload = json.loads(raw)
        payment.raw_webhook = payload["data"]
        db.commit()
        return cls.process_webhook(db, raw, signature)

    @classmethod
    def reconcile_stale_payments(
        cls,
        db: Session,
        *,
        config: Settings | None = None,
        limit: int = 50,
        references: set[str] | None = None,
    ) -> list[tuple[str, str]]:
        current = config or settings
        cutoff = now_utc() - timedelta(minutes=20)
        statement = select(Payment).where(
            Payment.status.in_((PaymentStatus.INITIATED, PaymentStatus.PENDING)),
            Payment.created_at < cutoff,
        )
        if references is not None:
            statement = statement.where(Payment.kora_reference.in_(references))
        payments = db.execute(statement.order_by(Payment.created_at).limit(limit)).scalars().all()
        results: list[tuple[str, str]] = []
        provider = get_kora_provider(current)
        for payment in payments:
            try:
                verification = provider.verify(payment.kora_reference, payment=payment)
            except KoraProviderError:
                results.append((payment.kora_reference, "verify_failed"))
                continue
            data = verification.get("data") or {}
            status = data.get("status")
            if status in (None, "pending", "processing"):
                payment.attempt_count += 1
                db.commit()
                results.append((payment.kora_reference, "pending"))
                continue
            if status != "success":
                cls.mark_failed(db, payment, "reconciled_no_charge", data)
                results.append((payment.kora_reference, "failed"))
                continue
            outcome = cls._process_verification(db, payment, verification, data)
            results.append((payment.kora_reference, outcome))
        return results
