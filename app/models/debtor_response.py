from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.db.enums import (
    DebtorResponseType,
    DisputeReasonType,
    PromiseStatus,
    pg_values,
)
from app.models.mixins import BaseMixin
from sqlalchemy import Enum as SQLEnum


class DebtorResponse(Base, BaseMixin):
    __tablename__ = "debtor_responses"

    transaction_id: Mapped[UUID] = mapped_column(
        ForeignKey("credit_transactions.id", ondelete="RESTRICT"), nullable=False
    )
    type: Mapped[DebtorResponseType] = mapped_column(
        SQLEnum(DebtorResponseType, name="debtor_response_type", values_callable=pg_values),
        nullable=False,
    )
    promised_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    promised_amount_kobo: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    promise_status: Mapped[PromiseStatus | None] = mapped_column(
        SQLEnum(PromiseStatus, name="promise_status", values_callable=pg_values),
        nullable=True,
    )
    dispute_reason: Mapped[DisputeReasonType | None] = mapped_column(
        SQLEnum(DisputeReasonType, name="dispute_reason_type", values_callable=pg_values),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "type <> 'promise' OR (promised_date IS NOT NULL AND promise_status IS NOT NULL)",
            name="ck_dr_promise_fields",
        ),
        CheckConstraint(
            "promised_amount_kobo IS NULL OR promised_amount_kobo > 0",
            name="ck_dr_promise_amount",
        ),
        CheckConstraint(
            "type = 'promise' OR promise_status IS NULL",
            name="ck_dr_promise_status_scope",
        ),
        CheckConstraint(
            "type <> 'dispute' OR (dispute_reason IS NOT NULL AND message IS NOT NULL "
            "AND char_length(trim(message)) > 0)",
            name="ck_dr_dispute_fields",
        ),
        CheckConstraint(
            "type = 'dispute' OR dispute_reason IS NULL",
            name="ck_dr_dispute_reason_scope",
        ),
        Index("ix_dr_transaction", "transaction_id", text("created_at DESC")),
        Index("ix_dr_promise_outcome", "type", "promise_status"),
        Index(
            "uq_dr_one_open_promise",
            "transaction_id",
            unique=True,
            postgresql_where=text("type = 'promise' AND promise_status = 'open'"),
        ),
        Index(
            "uq_dr_one_open_dispute",
            "transaction_id",
            unique=True,
            postgresql_where=text("type = 'dispute' AND resolved_at IS NULL"),
        ),
    )
