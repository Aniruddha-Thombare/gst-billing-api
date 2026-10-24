from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class AgingBuckets(BaseModel):
    """Outstanding amounts split by how late they are."""
    current: Decimal = Field(description="Not yet due")
    days_1_30: Decimal
    days_31_60: Decimal
    days_61_90: Decimal
    over_90: Decimal
    total: Decimal
    invoice_count: int


class ArAgingFiltersApplied(BaseModel):
    party_id: UUID | None = None
    due_date_from: date | None = None
    due_date_to: date | None = None
    invoice_date_from: date | None = None
    invoice_date_to: date | None = None


class ArAgingSummaryResponse(BaseModel):
    """
    Tenant-wide receivables aging. Balances are the CURRENT outstanding
    amounts; as_of_date only decides how late each invoice is.
    Refund due (money owed TO customers) is reported separately and is
    never netted against receivables.
    """
    as_of_date: date
    filters: ArAgingFiltersApplied
    buckets: AgingBuckets
    refund_due_total: Decimal
    refund_due_invoice_count: int
    note: str = "Balances are current as of today; as_of_date only sets the lateness of each invoice."


class ArAgingPartyRow(AgingBuckets):
    """One customer's aging row."""
    party_id: UUID
    party_name: str
    oldest_due_date: date = Field(description="Earliest effective due date among the party's open invoices")