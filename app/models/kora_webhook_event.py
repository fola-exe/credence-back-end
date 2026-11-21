from datetime import datetime
from typing import Any

from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import BaseMixin


class KoraWebhookEvent(Base, BaseMixin):
    __tablename__ = "kora_webhook_events"

    kora_reference: Mapped[str] = mapped_column(nullable=False)
    event: Mapped[str] = mapped_column(nullable=False)
    signature_ok: Mapped[bool] = mapped_column(nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    outcome: Mapped[str | None] = mapped_column(nullable=True)

    __table_args__ = (
        UniqueConstraint("kora_reference", "event", name="uq_kwe_ref_event"),
        Index("ix_kwe_created", "created_at"),
    )
