from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.core.logging import audit_event
from app.models import Business
from app.modules.businesses.schemas import BusinessProfile


class BusinessService:
    @staticmethod
    def get_profile(business: Business) -> BusinessProfile:
        return BusinessProfile.model_validate(business)

    @staticmethod
    def set_credit_limit(
        db: Session,
        business: Business,
        credit_limit_kobo: int | None,
        *,
        request_id: str | None = None,
    ) -> BusinessProfile:
        if credit_limit_kobo is not None and credit_limit_kobo <= 0:
            raise ValidationFailed(
                "The request is invalid.",
                fields={
                    "credit_limit_kobo": "Must be greater than 0, or null to remove the limit."
                },
            )

        old_limit = business.credit_limit_kobo
        business.credit_limit_kobo = credit_limit_kobo
        db.commit()
        db.refresh(business)

        audit_event(
            "business.credit_limit_changed",
            request_id=request_id,
            business_id=str(business.id),
            actor=f"business:{business.id}",
            old_credit_limit_kobo=old_limit,
            new_credit_limit_kobo=credit_limit_kobo,
        )
        return BusinessProfile.model_validate(business)
