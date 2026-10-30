"""GSTR-3B (outward side only) response schemas. Money is Decimal (serialised as a string)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.gstr1 import TaxAmounts, TenantSummary

ZERO = Decimal("0.00")


class Table32Row(BaseModel):
    """3.2: inter-state supplies to unregistered persons, by place of supply."""
    place_of_supply: str
    taxable_amount: Decimal = ZERO
    igst_amount: Decimal = ZERO


class Gstr3bReport(BaseModel):
    return_period: str
    financial_year: str
    tenant: TenantSummary
    generated_at: datetime
    is_period_open: bool

    outward_taxable: TaxAmounts = Field(default_factory=TaxAmounts, description="3.1(a)")
    outward_zero_rated: TaxAmounts = Field(default_factory=TaxAmounts, description="3.1(b) exports and SEZ")
    outward_nil_exempt: TaxAmounts = Field(default_factory=TaxAmounts, description="3.1(c)")
    outward_reverse_charge: TaxAmounts = Field(
        default_factory=TaxAmounts,
        description="Supplies where the RECIPIENT pays the tax. Shown for information, NOT added to total_outward.",
    )
    total_outward: TaxAmounts = Field(default_factory=TaxAmounts, description="3.1(a)+(b)+(c)")
    unregistered_interstate: list[Table32Row] = Field(default_factory=list, description="Table 3.2")
    warnings: list[str] = Field(default_factory=list)
