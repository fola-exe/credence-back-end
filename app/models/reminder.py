from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.db.enums import ReminderKind, ReminderStatus, pg_values
from app.models.mixins import BaseMixin
from sqlalchemy import Enum as SQLEnum


class Reminder(Base, BaseMixin):
    __tablename__ = "reminders"

    transaction_id: Mapped[UUID] = mapped_column(
        ForeignKey("credit_transactions.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[ReminderKind] = mapped_column(
        SQLEnum(ReminderKind, name="reminder_kind", values_callable=pg_values),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(
        String(16), nullable=False, default="email", server_default=text("'email'")
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[ReminderStatus] = mapped_column(
        SQLEnum(ReminderStatus, name="reminder_status", values_callable=pg_values),
        nullable=False,
        default=ReminderStatus.SCHEDULED,
        server_default=text("'scheduled'"),
    )
    skip_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("channel IN ('email')", name="ck_rem_channel"),
        CheckConstraint(
            "status <> 'sent' OR sent_at IS NOT NULL", name="ck_rem_sent_fields"
        ),
        CheckConstraint(
            "status <> 'skipped' OR skip_reason IS NOT NULL", name="ck_rem_skip_reason"
        ),
        Index(
            "ix_rem_due",
            "scheduled_for",
            postgresql_where=text("status = 'scheduled'"),
        ),
        Index("ix_rem_transaction", "transaction_id", "status", "scheduled_for"),
    )
