from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.db.enums import EventActor, pg_values
from app.models.mixins import BaseMixin
from sqlalchemy import Enum as SQLEnum


class TransactionEvent(Base, BaseMixin):
    __tablename__ = "transaction_events"

    transaction_id: Mapped[UUID] = mapped_column(
        ForeignKey("credit_transactions.id", ondelete="RESTRICT"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(48), nullable=False)
    actor: Mapped[EventActor] = mapped_column(
        SQLEnum(EventActor, name="event_actor", values_callable=pg_values),
        nullable=False,
    )
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        CheckConstraint(
            "type IN ('transaction_created','reminder_sent','reminder_failed',"
            "'debtor_acknowledged','promise_made','promise_kept','promise_missed',"
            "'payment_received','payment_failed','dispute_raised','dispute_resolved',"
            "'note_added','settled','cancelled')",
            name="ck_te_type",
        ),
        Index("ix_te_transaction", "transaction_id", text("created_at DESC")),
    )
