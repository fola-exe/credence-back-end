from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.db.enums import PaymentStatus, pg_values
from app.models.mixins import BaseMixin
from sqlalchemy import Enum as SQLEnum


class Payment(Base, BaseMixin):
    __tablename__ = "payments"

    transaction_id: Mapped[UUID] = mapped_column(
        ForeignKey("credit_transactions.id", ondelete="RESTRICT"), nullable=False
    )
    kora_reference: Mapped[str] = mapped_column(String(80), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    amount_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        SQLEnum(PaymentStatus, name="payment_status", values_callable=pg_values),
        nullable=False,
        default=PaymentStatus.INITIATED,
        server_default=text("'initiated'"),
    )
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    receipt_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    raw_webhook: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    overpaid_kobo: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    review_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_mode: Mapped[str] = mapped_column(
        String(8), nullable=False, default="sandbox", server_default=text("'sandbox'")
    )
    idempotency_key: Mapped[UUID | None] = mapped_column(nullable=True)

    __table_args__ = (
        UniqueConstraint("kora_reference", name="uq_pay_kora_reference"),
        UniqueConstraint("receipt_number", name="uq_pay_receipt_number"),
        UniqueConstraint("transaction_id", "attempt_number", name="uq_pay_attempt"),
        CheckConstraint("amount_kobo > 0", name="ck_pay_amount"),
        CheckConstraint(
            "status <> 'successful' OR "
            "(paid_at IS NOT NULL AND receipt_number IS NOT NULL AND verified_at IS NOT NULL)",
            name="ck_pay_success_fields",
        ),
        CheckConstraint(
            "overpaid_kobo IS NULL OR overpaid_kobo >= 0", name="ck_pay_overpaid"
        ),
        CheckConstraint(
            "review_reason IS NULL OR "
            "review_reason IN ('overpaid','paid_cancelled_transaction')",
            name="ck_pay_review_reason",
        ),
        CheckConstraint(
            "provider_mode IN ('sandbox','live')", name="ck_pay_provider_mode"
        ),
        Index("ix_pay_transaction", "transaction_id", "status"),
        Index(
            "ix_pay_received",
            "transaction_id",
            text("paid_at DESC"),
            postgresql_where=text("status = 'successful'"),
        ),
        Index(
            "ix_pay_stale",
            "created_at",
            postgresql_where=text("status IN ('initiated','pending')"),
        ),
        Index(
            "uq_pay_idempotency",
            "transaction_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "ix_pay_review",
            text("created_at DESC"),
            postgresql_where=text("review_reason IS NOT NULL"),
        ),
    )
