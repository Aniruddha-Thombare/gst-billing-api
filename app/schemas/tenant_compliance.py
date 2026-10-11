from datetime import date 
from decimal import Decimal 
from uuid import UUID 

from pydantic import BaseModel, Field, model_validator


# REGISTRATION 

class TenantComplianceCreate(BaseModel):
    """
    Accepts the compliance data for a single tenant 

    Called once per financial year when a new FY begins.
    The tenant's accountant submits the ACTUAL preceding year's
    aggregate annual turnover — this determines:
      1. Minimum HSN digit count on all invoices in this FY
      2. Whether e-invoice IRP registration is mandatory

    financial_year format: "YYYY-YY" e.g. "2025-26"
    """
    financial_year: str = Field(
        ..., 
        pattern=r"^[0-9]{4}-[0-9]{2}$",
        examples=["2026-27"],
    )

    annual_turnover: Decimal = Field(
        default=Decimal("0"), 
        ge=Decimal("0"),
        description="Aggregate annual turnover of the PRECEDING financial year.",
        examples=[Decimal("20000000.00")],
    )

    composition_turnover: Decimal = Field(
        default=Decimal("0"),
        ge=Decimal("0"),
    )

    is_msme: bool = Field(default=False)

    @classmethod
    @model_validator(mode="after")
    def validate_financial_year_suffix(self) -> "TenantComplianceCreate":
        parts = self.financial_year.split("-")
        start_year = parts[0]
        suffix = int(parts[1])
        expected = (start_year + 1 ) % 100
        if suffix != expected:
            raise ValueError(
                f"Financial year suffix must be {expected:02d} for start year {start_year}."
            )
        return self


class TenantComplianceResponse(BaseModel):
    model_config = {"from_attributes": True}

    tenant_id: UUID
    financial_year: str
    annual_turnover: Decimal 
    composition_turnover: Decimal 
    is_msme: bool 
    effective_from: date
    effective_to: date | None 
