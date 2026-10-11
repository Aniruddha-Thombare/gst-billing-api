from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class PartyBase(BaseModel):
    """
    Editable fields of a party (shared by create and update).

    gstin and pan are upper-cased and blank strings become None. The
    cross-field GSTIN / PAN / state rules need business_rules and are
    enforced in party_service.
    """
    name: str = Field(..., min_length=1, max_length=255)
    gstin: str | None = Field(default=None, pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
    pan: str | None = Field(default=None, pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")
    address_line1: str = Field(..., min_length=1, max_length=500)
    address_line2: str | None = Field(default=None, max_length=500)
    city: str = Field(..., min_length=1, max_length=100)
    pincode: str = Field(..., pattern=r"^[1-9][0-9]{5}$")
    state_code: str = Field(..., pattern=r"^[0-9]{2}$")
    email: str | None = Field(default=None, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str | None = Field(default=None, pattern=r"^[0-9+\-\s]{7,20}$")

    @field_validator("name", "city", "address_line1", mode="before")
    @classmethod
    def strip_text(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("gstin", "pan", mode="before")
    @classmethod
    def normalise_tax_ids(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            return v.strip().upper() or None
        return v

    @field_validator("state_code")
    @classmethod
    def state_code_in_range(cls, v: str) -> str:
        """GST state / UT codes are 01 to 38."""
        if not 1 <= int(v) <= 38:
            raise ValueError("state_code must be a valid GST state code (01-38).")
        return v


class PartyCreateRequest(PartyBase):
    """Body for POST /parties. party_type is fixed at creation."""
    party_type: str = Field(..., pattern=r"^(customer|vendor)$")


class PartyUpdateRequest(PartyBase):
    """Body for PUT /parties/{party_id}. Full replace of editable fields; party_type cannot change."""
    pass


class PartyResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    name: str
    gstin: str | None
    pan: str | None
    address_line1: str
    address_line2: str | None
    city: str
    pincode: str
    state_code: str
    email: str | None
    phone: str | None
    party_type: str
    is_active: bool
    created_at: datetime
    updated_at: datetime