from fastapi import APIRouter, Request, status

from app.core.dependencies import AuthenticatedBusiness, DatabaseSession
from app.modules.businesses.schemas import BusinessProfile, CreditLimitUpdate
from app.modules.businesses.service import BusinessService

business_routes = APIRouter(tags=["businesses"])


@business_routes.get("/business", response_model=BusinessProfile)
def get_business(business: AuthenticatedBusiness):
    return BusinessService.get_profile(business)


@business_routes.patch(
    "/business/credit-limit",
    response_model=BusinessProfile,
    status_code=status.HTTP_200_OK,
)
def set_credit_limit(
    payload: CreditLimitUpdate,
    db: DatabaseSession,
    business: AuthenticatedBusiness,
    request: Request,
):
    return BusinessService.set_credit_limit(
        db,
        business,
        payload.credit_limit_kobo,
        request_id=getattr(request.state, "request_id", None),
    )
