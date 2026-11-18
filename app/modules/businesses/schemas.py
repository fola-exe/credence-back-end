from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models import BusinessCategory


class BusinessProfile(BaseModel):
    id: UUID
    name: str
    email: EmailStr
    phone: str
    address: str
    registration_number: str
    category: BusinessCategory
    credit_limit_kobo: int | None
    logo_url: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CreditLimitUpdate(BaseModel):
    credit_limit_kobo: int | None

    model_config = ConfigDict(extra="forbid")
