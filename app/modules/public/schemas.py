from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.enums import DisputeReasonType


class PayRequest(BaseModel):
    amount_kobo: Annotated[int, Field(strict=True, gt=0)]

    model_config = ConfigDict(extra="forbid")


class PromiseRequest(BaseModel):
    promised_date: date
    promised_amount_kobo: Annotated[int | None, Field(strict=True, gt=0)] = None
    message: str | None = Field(default=None, max_length=1000)

    model_config = ConfigDict(extra="forbid")


class DisputeRequest(BaseModel):
    reason: DisputeReasonType
    message: str = Field(min_length=1, max_length=2000)

    model_config = ConfigDict(extra="forbid")


class DemoChargeRequest(BaseModel):
    outcome: Literal["success", "failed"]

    model_config = ConfigDict(extra="forbid")
