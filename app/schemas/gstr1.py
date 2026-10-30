from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ZERO = Decimal("0.00")

Gstr1Section = Literal["b2b", "b2b_rcm", "b2cl", "b2cs", "exp", "sez", "cdnr", "cdnur", "nil", "hsn", "docs"]


class TaxAmounts(BaseModel):
    taxable_amount: Decimal = ZERO
    igst_amount: Decimal = ZERO
    cgst_amount: Decimal = ZERO
    sgst_amount: Decimal = ZERO
    cess_amount: Decimal = ZERO


class RateLine(TaxAmounts):
    """One GST-rate slice of a document (GSTN reports each document rate-wise)."""
    gst_rate: Decimal


class OutwardDocument(TaxAmounts):
    """An invoice or note, with its rate-wise lines. Totals are per document, UNSIGNED."""
    invoice_id: UUID
    document_number: str
    document_date: date
    document_type: Literal["sales", "credit_note", "debit_note"]
    note_type: Literal["C", "D"] | None = None
    party_name: str
    party_gstin: str | None
    place_of_supply: str
    supply_type: str
    reverse_charge: bool
    document_value: Decimal
    original_document_number: str | None = None
    original_document_date: date | None = None
    items: list[RateLine] = Field(default_factory=list)


class B2CSRow(TaxAmounts):
    """Table 7: consolidated by (supply type, place of supply, rate); NET of credit notes."""
    supply_type: str
    place_of_supply: str
    gst_rate: Decimal
    document_count: int


class NilExemptRow(BaseModel):
    """Table 8. Nil-rated and exempt cannot be told apart from stored data: both are 0% lines."""
    supply_type: Literal["interstate", "intrastate"]
    receiver: Literal["registered", "unregistered"]
    taxable_amount: Decimal = ZERO
    document_count: int = 0


class HsnRow(TaxAmounts):
    """Table 12, NET of credit notes (credit-note quantity and value are negative)."""
    hsn_sac_code: str | None
    unit: str
    gst_rate: Decimal
    quantity: Decimal
    total_value: Decimal


class DocumentSeriesRow(BaseModel):
    """Table 13."""
    document_type: str
    series: str
    first_number: str
    last_number: str
    total_numbers: int
    cancelled: int
    net_issued: int


class SectionTotals(TaxAmounts):
    section: str
    document_count: int = 0


class TenantSummary(BaseModel):
    gstin: str
    legal_name: str
    state_code: str


class Gstr1Report(BaseModel):
    return_period: str
    financial_year: str
    tenant: TenantSummary
    generated_at: datetime
    b2cl_threshold: Decimal
    is_period_open: bool = Field(description="True while the return month has not finished yet.")

    b2b: list[OutwardDocument] = Field(default_factory=list)
    b2b_rcm: list[OutwardDocument] = Field(default_factory=list)
    b2cl: list[OutwardDocument] = Field(default_factory=list)
    b2cs: list[B2CSRow] = Field(default_factory=list)
    exp: list[OutwardDocument] = Field(default_factory=list)
    sez: list[OutwardDocument] = Field(default_factory=list)
    cdnr: list[OutwardDocument] = Field(default_factory=list)
    cdnur: list[OutwardDocument] = Field(default_factory=list)
    nil: list[NilExemptRow] = Field(default_factory=list)
    hsn: list[HsnRow] = Field(default_factory=list)
    docs: list[DocumentSeriesRow] = Field(default_factory=list)

    section_totals: list[SectionTotals] = Field(default_factory=list)
    net_totals: TaxAmounts = Field(
        default_factory=TaxAmounts,
        description="Sum of every tax-bearing section, credit notes subtracted.",
    )
    warnings: list[str] = Field(default_factory=list)