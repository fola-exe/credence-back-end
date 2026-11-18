from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.db.enums import CreditTransactionStatus, pg_values
from app.models.mixins import BaseMixin
from sqlalchemy import Enum as SQLEnum


class CreditTransaction(Base, BaseMixin):
    __tablename__ = "credit_transactions"

    business_id: Mapped[UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False
    )
    debtor_id: Mapped[UUID] = mapped_column(
        ForeignKey("debtors.id", ondelete="RESTRICT"), nullable=False
    )
    reference: Mapped[str] = mapped_column(String(20), nullable=False)
    invoice_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    amount_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CreditTransactionStatus] = mapped_column(
        SQLEnum(
            CreditTransactionStatus,
            name="credit_transaction_status",
            values_callable=pg_values,
        ),
        nullable=False,
        default=CreditTransactionStatus.PENDING_ACK,
        server_default=text("'pending_ack'"),
    )
    public_token: Mapped[str] = mapped_column(String(64), nullable=False)
    capacity_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_business_id: Mapped[UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("reference", name="uq_ct_reference"),
        UniqueConstraint("public_token", name="uq_ct_public_token"),
        CheckConstraint("amount_kobo > 0", name="ck_ct_amount"),
        CheckConstraint("due_date >= issue_date", name="ck_ct_due_after_issue"),
        CheckConstraint(
            "(capacity_override = false AND override_reason IS NULL) OR "
            "(capacity_override = true AND override_reason IS NOT NULL "
            "AND char_length(trim(override_reason)) > 0)",
            name="ck_ct_override_reason",
        ),
        CheckConstraint(
            "(status = 'settled') = (settled_at IS NOT NULL)", name="ck_ct_settled_at"
        ),
        Index("ix_ct_business_status", "business_id", "status"),
        Index("ix_ct_business_due", "business_id", "due_date"),
        Index("ix_ct_debtor", "debtor_id"),
        Index("ix_ct_business_created", "business_id", text("created_at DESC")),
        Index(
            "ix_ct_open_by_business",
            "business_id",
            postgresql_where=text("status NOT IN ('settled','cancelled')"),
        ),
    )
