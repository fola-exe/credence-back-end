from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

class DebtorCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    contact_person: str | None = Field(default=None, max_length=120)
    email: EmailStr
    phone: str
    credit_limit_kobo: int | None = Field(default=None, gt=0)
    address: str | None = None

    model_config = ConfigDict(extra="forbid")


class DebtorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    contact_person: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = None
    phone: str | None = None
    credit_limit_kobo: int | None = Field(default=None, gt=0)
    address: str | None = None

    model_config = ConfigDict(extra="forbid")


class DebtorSummary(BaseModel):
    id: UUID
    name: str
    contact_person: str | None
    email: EmailStr
    phone: str
    credit_limit_kobo: int | None
    outstanding_kobo: int
    overdue_kobo: int
    open_disputes: int
    has_open_promise: bool
    score: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
