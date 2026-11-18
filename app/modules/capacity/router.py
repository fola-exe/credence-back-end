from uuid import UUID

from fastapi import APIRouter

from app.core.dependencies import AuthenticatedBusiness, DatabaseSession
from app.modules.capacity.service import CreditCapacityService

capacity_routes = APIRouter(tags=["capacity"])


@capacity_routes.get("/capacity")
def check_capacity(
    amount_kobo: int,
    db: DatabaseSession,
    business: AuthenticatedBusiness,
    debtor_id: UUID | None = None,
    debtor_limit_kobo: int | None = None,
):
    return CreditCapacityService.check(
        db,
        business,
        amount_kobo,
        debtor_id=debtor_id,
        debtor_limit_kobo=debtor_limit_kobo,
    )
