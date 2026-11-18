from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import BaseMixin


class Debtor(Base, BaseMixin):
    __tablename__ = "debtors"

    business_id: Mapped[UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    contact_person: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    credit_limit_kobo: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("char_length(name) >= 2", name="ck_debtors_name_len"),
        CheckConstraint(
            "credit_limit_kobo IS NULL OR credit_limit_kobo > 0",
            name="ck_debtors_credit_limit",
        ),
        CheckConstraint(
            "phone ~ '^\\+[1-9][0-9]{9,14}$'", name="ck_debtors_phone_e164"
        ),
        Index("uq_debtors_business_email", "business_id", func.lower(email), unique=True),
        Index("ix_debtors_business_name", "business_id", func.lower(name)),
    )
