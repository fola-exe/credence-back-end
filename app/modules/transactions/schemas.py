from datetime import date
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.debtors.schemas import DebtorCreate


class CreateTransactionSchema(BaseModel):
    debtor_id: UUID | None = None
    new_debtor: DebtorCreate | None = None
    description: str = Field(min_length=1, max_length=200)
    amount_kobo: Annotated[int, Field(strict=True, gt=0, le=9_000_000_000_000)]
    issue_date: date
    due_date: date
    invoice_number: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=2000)
    override: bool = False
    override_reason: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def check_debtor_choice(self):
        if (self.debtor_id is None) == (self.new_debtor is None):
            raise ValueError("Send exactly one of debtor_id or new_debtor")
        if self.override and (not self.override_reason or not self.override_reason.strip()):
            raise ValueError("override_reason is required when override is true")
        if not self.override and self.override_reason is not None:
            raise ValueError("override_reason must be absent when override is false")
        return self
