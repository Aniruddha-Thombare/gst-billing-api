"""Sales-summary response schemas (read-only business report)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

ZERO = Decimal("0.00")


class SalesBucket(BaseModel):
    period_label: str
    period_start: date
    period_end: date
    sales_count: int = 0
    credit_note_count: int = 0
    debit_note_count: int = 0
    gross_sales_value: Decimal = ZERO      # sales + debit notes, line totals incl. tax
    credit_note_value: Decimal = ZERO      # shown positive, as stored
    net_sales_value: Decimal = ZERO        # gross - credit notes
    net_taxable_amount: Decimal = ZERO
    net_tax_amount: Decimal = ZERO         # IGST + CGST + SGST + cess, net of credit notes


class SalesSummaryReport(BaseModel):
    granularity: str
    from_date: date
    to_date: date
    generated_at: datetime
    buckets: list[SalesBucket] = Field(default_factory=list)
    totals: SalesBucket
