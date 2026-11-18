from uuid import UUID

from fastapi import APIRouter

from app.core.dependencies import AuthenticatedBusiness, DatabaseSession
from app.modules.debtors.schemas import DebtorCreate, DebtorUpdate
from app.modules.debtors.service import DebtorService

debtor_routes = APIRouter(tags=["debtors"])


@debtor_routes.get("/debtors")
def list_debtors(
    db: DatabaseSession,
    business: AuthenticatedBusiness,
    q: str | None = None,
    page: int | None = None,
    limit: int | None = None,
):
    return DebtorService.list(db, business.id, q, page, limit)


@debtor_routes.post("/debtors", status_code=201)
def create_debtor(
    payload: DebtorCreate,
    db: DatabaseSession,
    business: AuthenticatedBusiness,
):
    return DebtorService.create(db, business.id, payload)


@debtor_routes.get("/debtors/{debtor_id}")
def get_debtor(
    debtor_id: UUID,
    db: DatabaseSession,
    business: AuthenticatedBusiness,
    page: int | None = None,
    limit: int | None = None,
):
    return DebtorService.get_profile(db, business.id, debtor_id, page, limit)


@debtor_routes.patch("/debtors/{debtor_id}")
def update_debtor(
    debtor_id: UUID,
    payload: DebtorUpdate,
    db: DatabaseSession,
    business: AuthenticatedBusiness,
):
    return DebtorService.update(db, business.id, debtor_id, payload)
