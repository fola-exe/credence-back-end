from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import (
    AmountOutOfRange,
    DisputeAlreadyOpen,
    IdempotencyKeyReused,
    PaymentInitFailed,
    TransactionNotPayable,
    TransactionNotFound,
)
from app.core.logging import log_event
from app.core.time import now_utc, today_wat
from app.db.enums import (
    CreditTransactionStatus,
    DebtorResponseType,
    EventActor,
    PaymentStatus,
    ReminderStatus,
)
from app.integrations.email.client import email_service
from app.integrations.kora.client import get_kora_provider
from app.models import CreditTransaction, DebtorResponse, Debtor, Business, Payment, Reminder
from app.modules.promises.service import PromiseService
from app.modules.public.projection import open_dispute, public_transaction
from app.modules.transactions.balance import balance_for, display_status
from app.modules.transactions.events import record


class PublicService:
    @staticmethod
    def get_transaction(db: Session, token: str) -> CreditTransaction:
        transaction = db.execute(
            select(CreditTransaction).where(CreditTransaction.public_token == token)
        ).scalars().first()
        if transaction is None:
            raise TransactionNotFound()
        return transaction

    @staticmethod
    def _locked_transaction(db: Session, token: str) -> CreditTransaction:
        transaction = db.execute(
            select(CreditTransaction)
            .where(CreditTransaction.public_token == token)
            .with_for_update()
        ).scalars().first()
        if transaction is None:
            raise TransactionNotFound()
        return transaction

    @classmethod
    def detail(cls, db: Session, token: str) -> dict:
        return public_transaction(db, cls.get_transaction(db, token))

    @classmethod
    def acknowledge(cls, db: Session, token: str) -> dict:
        transaction = cls._locked_transaction(db, token)
        if transaction.status == CreditTransactionStatus.PENDING_ACK:
            transaction.status = CreditTransactionStatus.ACTIVE
            transaction.acknowledged_at = now_utc()
            record(
                db,
                transaction.id,
                "debtor_acknowledged",
                EventActor.DEBTOR,
                {"debtor_name": db.get(Debtor, transaction.debtor_id).name},
            )
        elif transaction.status not in (
            CreditTransactionStatus.SETTLED,
            CreditTransactionStatus.CANCELLED,
        ):
            if transaction.acknowledged_at is None:
                transaction.acknowledged_at = now_utc()
        db.commit()
        balance = balance_for(db, transaction)
        return {
            "status": transaction.status.value,
            "display_status": display_status(
                transaction, balance.outstanding_kobo, today_wat()
            ).value,
            "acknowledged_at": transaction.acknowledged_at,
        }

    @staticmethod
    def _reference(transaction: CreditTransaction, attempt: int) -> str:
        template = settings.kora_reference_format or "{reference}-P{attempt}"
        return template.format(reference=transaction.reference, attempt=attempt)

    @staticmethod
    def _payment_result(payment: Payment) -> dict:
        return {
            "checkout_url": payment.checkout_url,
            "reference": payment.kora_reference,
            "amount_kobo": payment.amount_kobo,
            "payment_id": str(payment.id),
        }

    @classmethod
    def initiate_payment(
        cls,
        db: Session,
        token: str,
        amount_kobo: int,
        idempotency_key: UUID | None = None,
    ) -> tuple[dict, int]:
        transaction = cls._locked_transaction(db, token)
        if transaction.status in (
            CreditTransactionStatus.SETTLED,
            CreditTransactionStatus.CANCELLED,
        ):
            raise TransactionNotPayable()
        balance = balance_for(db, transaction)
        if balance.outstanding_kobo == 0:
            raise TransactionNotPayable()
        if amount_kobo > balance.outstanding_kobo or (
            amount_kobo < 10_000 and amount_kobo != balance.outstanding_kobo
        ):
            raise AmountOutOfRange()

        if idempotency_key is not None:
            existing = db.execute(
                select(Payment).where(
                    Payment.transaction_id == transaction.id,
                    Payment.idempotency_key == idempotency_key,
                )
            ).scalars().first()
            if existing is not None:
                if existing.amount_kobo != amount_kobo:
                    raise IdempotencyKeyReused()
                if existing.status == PaymentStatus.FAILED:
                    raise IdempotencyKeyReused()
                return cls._payment_result(existing), 200

        attempt = int(
            db.execute(
                select(func.coalesce(func.max(Payment.attempt_number), 0)).where(
                    Payment.transaction_id == transaction.id
                )
            ).scalar_one()
            + 1
        )
        reference = cls._reference(transaction, attempt)
        payment = Payment(
            transaction_id=transaction.id,
            kora_reference=reference,
            attempt_number=attempt,
            amount_kobo=amount_kobo,
            status=PaymentStatus.INITIATED,
            provider_mode=settings.provider_mode,
            idempotency_key=idempotency_key,
        )
        db.add(payment)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            if idempotency_key is not None:
                existing = db.execute(
                    select(Payment).where(
                        Payment.transaction_id == transaction.id,
                        Payment.idempotency_key == idempotency_key,
                    )
                ).scalars().first()
                if existing is not None:
                    if existing.amount_kobo != amount_kobo:
                        raise IdempotencyKeyReused() from exc
                    return cls._payment_result(existing), 200
            raise
        db.refresh(payment)

        debtor = db.get(Debtor, transaction.debtor_id)
        redirect_url = (
            f"{settings.user_facing_url}/pay/{transaction.public_token}/result?ref={reference}"
        )
        notification_url = f"{settings.app_url}/webhooks/kora"
        try:
            result = get_kora_provider().initialize(
                amount_kobo=amount_kobo,
                reference=reference,
                customer={"name": debtor.name, "email": debtor.email},
                redirect_url=redirect_url,
                notification_url=notification_url,
                metadata={"transaction_id": str(transaction.id)},
            )
        except Exception as exc:
            payment.status = PaymentStatus.FAILED
            payment.failure_reason = str(exc)[:500]
            record(
                db,
                transaction.id,
                "payment_failed",
                EventActor.SYSTEM,
                {"amount_kobo": amount_kobo, "reason": str(exc)[:200]},
            )
            db.commit()
            raise PaymentInitFailed(str(exc)) from exc

        data = result.get("data", {})
        fresh = db.execute(
            select(Payment).where(Payment.id == payment.id).with_for_update()
        ).scalars().one()
        if fresh.status in (PaymentStatus.SUCCESSFUL, PaymentStatus.FAILED):
            return cls._payment_result(fresh), 200
        fresh.status = PaymentStatus.PENDING
        fresh.checkout_url = data.get("checkout_url")
        db.commit()
        db.refresh(fresh)
        return cls._payment_result(fresh), 201

    @classmethod
    def payment_status(cls, db: Session, token: str, reference: str) -> dict:
        transaction = cls.get_transaction(db, token)
        payment = db.execute(
            select(Payment).where(
                Payment.transaction_id == transaction.id,
                Payment.kora_reference == reference,
            )
        ).scalars().first()
        if payment is None:
            from app.core.errors import PaymentNotFound

            raise PaymentNotFound()
        balance = balance_for(db, transaction)
        return {
            "reference": payment.kora_reference,
            "amount_kobo": payment.amount_kobo,
            "status": payment.status.value,
            "paid_at": payment.paid_at,
            "provider_mode": payment.provider_mode,
            "receipt_number": payment.receipt_number,
            "receipt_url": (
                f"/public/tx/{transaction.public_token}/receipts/{payment.receipt_number}"
                if payment.receipt_number
                else None
            ),
            "failure_message": payment.failure_reason,
            "transaction": {
                "outstanding_kobo": balance.outstanding_kobo,
                "display_status": display_status(
                    transaction, balance.outstanding_kobo, today_wat()
                ).value,
            },
        }

    @classmethod
    def make_promise(cls, db: Session, token: str, payload) -> tuple[dict, int]:
        transaction = cls.get_transaction(db, token)
        return PromiseService.make(db, transaction, payload)

    @classmethod
    def create_dispute(cls, db: Session, token: str, payload) -> tuple[dict, int]:
        transaction = cls._locked_transaction(db, token)
        if transaction.status in (
            CreditTransactionStatus.SETTLED,
            CreditTransactionStatus.CANCELLED,
        ):
            raise TransactionNotPayable()
        existing = open_dispute(db, transaction.id)
        if existing is not None:
            if (
                existing.dispute_reason == payload.reason
                and existing.message == payload.message
            ):
                return (
                    {
                        "dispute": {
                            "id": existing.id,
                            "reason": existing.dispute_reason.value,
                            "message": existing.message,
                            "created_at": existing.created_at,
                        },
                        "transaction": {
                            "status": transaction.status.value,
                            "display_status": display_status(
                                transaction, balance_for(db, transaction).outstanding_kobo, today_wat()
                            ).value,
                        },
                        "reminders_cancelled": 0,
                    },
                    200,
                )
            raise DisputeAlreadyOpen()

        dispute = DebtorResponse(
            transaction_id=transaction.id,
            type=DebtorResponseType.DISPUTE,
            dispute_reason=payload.reason,
            message=payload.message,
        )
        db.add(dispute)
        transaction.status = CreditTransactionStatus.DISPUTED
        if transaction.acknowledged_at is None:
            transaction.acknowledged_at = now_utc()
        cancelled = db.execute(
            select(func.count())
            .select_from(Reminder)
            .where(
                Reminder.transaction_id == transaction.id,
                Reminder.status == ReminderStatus.SCHEDULED,
            )
        ).scalar_one()
        for reminder in db.scalars(
            select(Reminder).where(
                Reminder.transaction_id == transaction.id,
                Reminder.status == ReminderStatus.SCHEDULED,
            )
        ).all():
            reminder.status = ReminderStatus.CANCELLED
            reminder.skip_reason = "disputed"
        record(
            db,
            transaction.id,
            "dispute_raised",
            EventActor.DEBTOR,
            {
                "reason": payload.reason.value,
                "message": payload.message,
                "reminders_cancelled": int(cancelled),
            },
        )
        db.commit()
        db.refresh(dispute)

        business = db.get(Business, transaction.business_id)
        debtor = db.get(Debtor, transaction.debtor_id)
        try:
            email_service.send(
                "creditor_notice",
                to=business.email,
                context={
                    "business_name": business.name,
                    "debtor_name": debtor.name,
                    "reference": transaction.reference,
                    "response_summary": f"{debtor.name} raised a dispute: {payload.reason.value}",
                },
            )
        except Exception as exc:
            log_event(
                "email_failed",
                template="creditor_notice",
                reference=transaction.reference,
                error=str(exc),
            )
        return (
            {
                "dispute": {
                    "id": dispute.id,
                    "reason": dispute.dispute_reason.value,
                    "message": dispute.message,
                    "created_at": dispute.created_at,
                },
                "transaction": {
                    "status": transaction.status.value,
                    "display_status": display_status(
                        transaction, balance_for(db, transaction).outstanding_kobo, today_wat()
                    ).value,
                },
                "reminders_cancelled": int(cancelled),
            },
            201,
        )
