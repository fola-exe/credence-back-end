from fastapi import APIRouter, status

from app.core.dependencies import AuthenticatedBusiness, DatabaseSession
from app.modules.transactions.schemas import CreateTransactionSchema
from app.modules.transactions.service import CreditTransactionService

transaction_routes = APIRouter(tags=["transactions"])


@transaction_routes.post("/transactions", status_code=status.HTTP_201_CREATED)
def create_transaction(
    payload: CreateTransactionSchema,
    db: DatabaseSession,
    business: AuthenticatedBusiness,
):
    return CreditTransactionService.create(db, business, payload)
