from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import CapacityExceeded, NotFound, ValidationFailed
from app.models import Business, Debtor
from app.modules.businesses.queries import business_outstanding, debtor_outstanding


class CreditCapacityService:
    @staticmethod
    def _block(limit: int | None, outstanding: int, amount_kobo: int) -> dict:
        return {
            "limit": limit,
            "outstanding": outstanding,
            "available": (
                limit - outstanding if limit is not None else None
            ),
            "_ok": limit is None or outstanding + amount_kobo <= limit,
            "_over_by": (
                max(0, outstanding + amount_kobo - limit) if limit is not None else 0
            ),
        }

    @classmethod
    def check(
        cls,
        db: Session,
        business: Business,
        amount_kobo: int,
        debtor_id: UUID | None = None,
        debtor_limit_kobo: int | None = None,
    ) -> dict:
        if debtor_id is not None and debtor_limit_kobo is not None:
            raise ValidationFailed(
                "The request is invalid.",
                fields={
                    "debtor_id": "Send debtor_id or debtor_limit_kobo, not both."
                },
            )

        business_block = cls._block(
            business.credit_limit_kobo,
            business_outstanding(db, business.id),
            amount_kobo,
        )

        debtor = None
        if debtor_id is not None:
            debtor = db.query(Debtor).filter(
                Debtor.id == debtor_id, Debtor.business_id == business.id
            ).first()
            if debtor is None:
                raise NotFound("Debtor not found")
            debtor_block = cls._block(
                debtor.credit_limit_kobo,
                debtor_outstanding(db, business.id, debtor.id),
                amount_kobo,
            )
        elif debtor_limit_kobo is not None:
            debtor_block = cls._block(debtor_limit_kobo, 0, amount_kobo)
        else:
            debtor_block = None

        business_ok = business_block.pop("_ok")
        business_over = business_block.pop("_over_by")
        if debtor_block is not None:
            debtor_ok = debtor_block.pop("_ok")
            debtor_over = debtor_block.pop("_over_by")
        else:
            debtor_ok = True
            debtor_over = 0

        return {
            "business": business_block,
            "debtor": debtor_block,
            "after_this": {"business_ok": business_ok, "debtor_ok": debtor_ok},
            "requires_override": not business_ok or not debtor_ok,
            "over_by_kobo": {"business": business_over, "debtor": debtor_over},
        }

    @classmethod
    def assert_within_limit(
        cls,
        db: Session,
        business: Business,
        amount_kobo: int,
        *,
        override: bool,
        override_reason: str | None,
        debtor_id: UUID | None = None,
    ) -> dict:
        result = cls.check(db, business, amount_kobo, debtor_id=debtor_id)
        if result["requires_override"] and not (override and override_reason):
            raise CapacityExceeded()
        return result
