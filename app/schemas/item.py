from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ItemWriteRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    hsn_sac_code: str | None = Field(default=None, pattern=r"^\d{2,8}$")
    unit: str = Field(default="PCS", min_length=1, max_length=10)
    rate: Decimal = Field(ge=0, max_digits=17, decimal_places=2)
    gst_rate: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    cess_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=5, decimal_places=2)
    is_service: bool = False

    @field_validator("unit")
    @classmethod
    def _upper_unit(cls, value: str) -> str:
        return value.upper()


class ItemCreateRequest(ItemWriteRequest):
    pass


class ItemUpdateRequest(ItemWriteRequest):
    """Full replace of the editable fields, same convention as parties."""


class ItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    hsn_sac_code: str | None
    unit: str
    rate: Decimal
    gst_rate: Decimal
    cess_rate: Decimal
    is_service: bool
    is_active: bool
    created_at: datetime