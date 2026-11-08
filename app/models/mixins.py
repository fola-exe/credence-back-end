from sqlalchemy import func, DateTime, Uuid
from sqlalchemy.orm import Mapped, mapped_column, declared_attr
from datetime import datetime
import uuid

class BaseMixin:
    @declared_attr
    def id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            Uuid,
            primary_key=True,
            default=uuid.uuid4
        )

    @declared_attr
    def created_at(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            default=func.now(),
            nullable=False
        )

    @declared_attr
    def updated_at(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            default=func.now(),
            onupdate=func.now(),
            nullable=False
        )