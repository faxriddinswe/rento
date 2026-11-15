from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MeterKind = Literal["electricity", "water_cold", "water_hot", "gas", "heating", "other"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PropertyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: str = Field(default="", max_length=500)


class PropertyPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=500)


class PropertyOut(ORM):
    id: UUID
    name: str
    address: str
    owner_id: UUID


class ManagerIn(BaseModel):
    email: str
    full_name: str = Field(min_length=1, max_length=200)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    permissions: list[str]


class ManagerOut(BaseModel):
    user_id: UUID
    email: str
    full_name: str
    permissions: list[str]


class UnitIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    area_m2: Decimal | None = Field(default=None, ge=0)


class UnitOut(ORM):
    id: UUID
    property_id: UUID
    name: str
    area_m2: Decimal | None


class LeaseIn(BaseModel):
    start_date: date
    end_date: date | None = None
    monthly_rent: int = Field(ge=0, description="minor units (tiyin)")
    deposit: int = Field(default=0, ge=0)
    billing_day: int = Field(default=1, ge=1, le=28)
    due_days: int = Field(default=10, ge=0, le=60)

    @model_validator(mode="after")
    def _dates(self) -> "LeaseIn":
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class LeaseEndIn(BaseModel):
    end_date: date


class LeaseOut(ORM):
    id: UUID
    unit_id: UUID
    tenant_id: UUID | None
    start_date: date
    end_date: date | None
    monthly_rent: int
    deposit: int
    billing_day: int
    due_days: int
    status: str


class InviteIn(BaseModel):
    email: str
    full_name: str = Field(min_length=1, max_length=200)


class InviteOut(BaseModel):
    invite_id: UUID
    token: str
    url: str
    expires_at: datetime


class MeterIn(BaseModel):
    kind: MeterKind
    serial: str = Field(default="", max_length=100)
    unit_label: str = Field(default="", max_length=16)


class MeterPatch(BaseModel):
    serial: str | None = Field(default=None, max_length=100)
    unit_label: str | None = Field(default=None, max_length=16)
    is_active: bool | None = None


class MeterOut(ORM):
    id: UUID
    unit_id: UUID
    kind: str
    serial: str
    unit_label: str
    is_active: bool


class Tier(BaseModel):
    up_to: Decimal | None = Field(
        default=None, gt=0, description="upper bound of tier; null = open"
    )
    price: Decimal = Field(ge=0, description="minor units per unit")


class TariffIn(BaseModel):
    kind: MeterKind
    name: str = Field(default="", max_length=200)
    effective_from: date
    unit_price: Decimal = Field(ge=0, description="minor units per unit of consumption")
    tiers: list[Tier] | None = None

    @field_validator("tiers")
    @classmethod
    def _tiers(cls, v: list[Tier] | None) -> list[Tier] | None:
        if v is None:
            return v
        if not v:
            raise ValueError("tiers must not be empty")
        bounds = [t.up_to for t in v]
        if bounds[-1] is not None or any(b is None for b in bounds[:-1]):
            raise ValueError("only the last tier may be open-ended (up_to = null)")
        finite = [b for b in bounds if b is not None]
        if finite != sorted(set(finite)):
            raise ValueError("tier bounds must be strictly increasing")
        return v


class TariffOut(ORM):
    id: UUID
    property_id: UUID
    kind: str
    name: str
    effective_from: date
    effective_to: date | None
    unit_price: Decimal
    tiers: list[Tier] | None


class PhotoUploadIn(BaseModel):
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    size: int = Field(gt=0, description="declared size in bytes")


class PhotoUploadOut(BaseModel):
    url: str
    fields: dict[str, str]
    key: str
    max_bytes: int


class ReadingIn(BaseModel):
    value: Decimal = Field(ge=0, max_digits=14, decimal_places=3)
    reading_date: date
    photo_key: str = Field(min_length=1, max_length=500)


class BaselineIn(BaseModel):
    """Owner/manager records a new baseline (first reading, or the meter was replaced)."""

    value: Decimal = Field(ge=0, max_digits=14, decimal_places=3)
    reading_date: date
    replaced_final_value: Decimal | None = Field(
        default=None, ge=0, max_digits=14, decimal_places=3
    )


class ConfirmIn(BaseModel):
    meter_replaced: bool = False
    replaced_final_value: Decimal | None = Field(
        default=None, ge=0, max_digits=14, decimal_places=3
    )


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class ReadingOut(ORM):
    id: UUID
    meter_id: UUID
    lease_id: UUID | None
    submitted_by: UUID
    value: Decimal
    reading_date: date
    status: str
    is_baseline: bool
    replaced_final_value: Decimal | None
    reject_reason: str | None
    photo_key: str | None
    photo_url: str | None = None
    created_at: datetime


class InvoiceLineOut(ORM):
    id: UUID
    sort: int
    kind: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: int
    meter_id: UUID | None
    pending_reading: bool


class InvoiceOut(ORM):
    id: UUID
    lease_id: UUID
    number: str
    period_start: date
    period_end: date
    issue_date: date
    due_date: date
    total: int
    previous_balance: int
    status: str
    paid: int = 0
    remaining: int = 0
    lines: list[InvoiceLineOut] = []


class BillingRunIn(BaseModel):
    through: date | None = Field(
        default=None, description="bill all periods up to this date (default today)"
    )


class BillingRunOut(BaseModel):
    created: int
    exists: int
    skipped: int
    missing_tariff: int
    invoice_ids: list[UUID]


class AdjustmentIn(BaseModel):
    amount: int = Field(description="minor units; negative = discount")
    description: str = Field(min_length=1, max_length=500)

    @field_validator("amount")
    @classmethod
    def _nonzero(cls, v: int) -> int:
        if v == 0:
            raise ValueError("amount must not be zero")
        return v


class AdjustmentOut(ORM):
    id: UUID
    lease_id: UUID
    amount: int
    description: str
    invoice_id: UUID | None
