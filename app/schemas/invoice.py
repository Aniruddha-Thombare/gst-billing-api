from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from app.domain.tax_engine import GST_RATE_SLABS
from app.models.enum import InvoiceStatus

class LineItemCreate(BaseModel):
    """
    Represents a single product or service line item within an invoice.

    Each invoice can contain one or more line items. This schema captures
    the details required to calculate taxable value and GST for an individual
    item before it is stored in the invoice.
    """
    description: Annotated[
        str, 
        StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]

    hsn_sac_code: str | None = Field(
        default= None,
        pattern=r"^[0-9]{4,8}$",
        description="HSN (goods, numeric, 4 - 8 digits) or SAC (services, 99XXXX, 6 digits)"
    )

    quantity: Decimal = Field(
        ..., gt=0,
        decimal_places=3, 
        le=Decimal("99999999.999")
    )
    
    unit: str | None = Field(default=None, max_length=10)

    rate: Decimal = Field(..., gt=0, decimal_places=4, le=Decimal("9999999999.9999"))

    discount_percent: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100"), decimal_places=2)

    # gst_rate validated against the EXACT statutory slab set from tax_engine.
    # Importing GST_RATE_SLABS here means this schema and the domain layer
    # can NEVER drift — one constant, two consumers.
    gst_rate: Decimal = Field(..., ge=0)

    cess_rate: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100"))

    @field_validator("gst_rate")
    @classmethod
    def validate_gst_rate_is_statutory(cls, v:Decimal) -> Decimal:
        """
        Rejects any rate not in tax_engine.GST_RATE_SLABS at the schema boundary - 
        a 422 here is cheaper than a 422 raised deep inside invoice_service after
        partial domain processing has already run. 

        """
        if v not in GST_RATE_SLABS:
            raise ValueError(
                f"GST rate {v}% is not a valid statutory slab. "
                f"Allowed GST rates: 0, 0.1, 0.125, 0.25, 0.75, 1, 1.5, 2.5, "
                f"3, 5, 6, 7.5, 9, 12, 14, 18, 28, 40."
            )
        return v


class InvoiceCreateRequest(BaseModel):
    """
    Represents the complete request to create an invoice.

    Contains invoice-level information such as customer details, invoice date,
    and a collection of line items. The system validates and calculates all
    invoice totals from the provided line items before creating the invoice.
    """
    invoice_type: str = Field(
        ..., pattern=r"^(sales|purchase|debit_note|credit_note)$", 
    )

    invoice_date: date 

    due_date: date | None = None 

    party_id: UUID 

    # To know whether dealing in goods or dealing in services.
    is_service: bool = Field(default=False)

    # Required for credit_note/debit_note. 
    original_invoice_id: UUID | None = None 

    # max_length=100 - Domain constraint. An invoice with > 100 line items is 
    # a data modelling error(likely should be multiple invoices). Capping here
    # also bounds the per-request tax-calculation workload to one lineitem. 
    # calculate_line_item_tax() runs once per line item synchronously.
    line_items: list[LineItemCreate] = Field(..., min_length=1, max_length=100)

    # client-declared grand total - validated against server computation by 
    # ledger_rules.validate_invoice_arithmetic() in invoice_service. 
    declared_grand_total: Decimal = Field(...,ge=0)

    notes: str | None = Field(default=None, max_length=2000)
    terms: str | None = Field(default=None, max_length=2000)

    confirm_duplicate: bool = Field(
        default=False,
        description="Set true only when re-submitting a sales/purchase invoice flagged as a "
                    "possible duplicate. Ignored for credit_note — those are hard-blocked, no override.",
    )

    @field_validator("invoice_date")
    @classmethod
    def validate_invoice_date_not_future(cls, v: date) -> date:
        """
        An invoice cannot be dated in the future. GST law requires invoices to 
        be issued for transactions that have occurred or are occurring - a future-
        dated tax  
        """
        if v > date.today():
            raise ValueError("Invoice date cannot be in the future")
        return v
    
    @model_validator(mode="after")
    def validate_due_date(self) -> "InvoiceCreateRequest":
        """
        Ensuring the validation for due date. A due date of an Invoice can be equal 
        to the invoice date, it must issued at future but not before the invoice date period. 
        """
        if self.due_date is not None and self.due_date < self.invoice_date:
            raise ValueError("Due date must be current dated or future dated")
        return self 

    @model_validator(mode="after")
    def validate_credit_debit_note_reference(self) -> "InvoiceCreateRequest":
        """
        CROSS-FIELD VALIDATION:
        credit_note / debit_note MUST reference an original_invoice_id.
        sales / purchase invoices MUST NOT — a regular sales invoice has
        no "original" to correct.

        This runs AFTER all individual field validators (mode="after"),
        so self.invoice_type and self.original_invoice_id are both
        guaranteed to have passed their own constraints already.
        """
        requires_reference = self.invoice_type in ("credit_note", "debit_note")

        if requires_reference and self.original_invoice_id is None:
            raise ValueError(
                f"invoice_type='{self.invoice_type}' requires original_invoice_id."
            )
        if not requires_reference and self.original_invoice_id is not None:
            raise ValueError(
                f"original_invoice_id must not be set for invoice_type='{self.invoice_type}'."
            )
        return self


class LineItemResponse(BaseModel):
    """
    Represents a single invoice line item returned by the API.

    Contains product details, pricing, discount information,
    GST breakdown, and final calculated amount.
    """
    model_config={"from_attributes": True}

    id: UUID
    line_number: int
    description: str
    hsn_sac_code: str | None 
    quantity: Decimal 
    unit: str | None 
    rate: Decimal 
    discount_percent: Decimal 
    discount_amount: Decimal 
    taxable_amount: Decimal 
    gst_rate: Decimal
    cgst_rate: Decimal 
    sgst_rate: Decimal 
    igst_rate: Decimal 
    cgst_amount: Decimal 
    sgst_amount: Decimal 
    igst_amount: Decimal 
    cess_rate: Decimal 
    cess_amount: Decimal 
    total_amount: Decimal 


class InvoiceResponse(BaseModel):
    """
    Represents a complete invoice returned by the API.

    Includes invoice details, party snapshot, tax totals,
    payment information, and all invoice line items.
    """
    model_config = {"from_attributes": True}

    id: UUID
    tenant_id: UUID
    invoice_number: str
    invoice_type: str
    invoice_date: date
    due_date: date | None
    financial_year: str
    party_id: UUID 
    party_gstin: str | None 
    party_state_code: str
    supply_type: str
    place_of_supply: str 
    reverse_charge: bool
    subtotal: Decimal 
    discount_amount: Decimal 
    taxable_amount: Decimal 
    cgst_amount: Decimal 
    sgst_amount: Decimal 
    igst_amount: Decimal 
    cess_amount: Decimal 
    total_amount: Decimal 
    paid_amount: Decimal 
    credited_amount: Decimal 
    refunded_amount: Decimal 
    outstanding_amount: Decimal 
    refund_due_amount: Decimal
    invoice_status: InvoiceStatus
    notes: str | None 
    terms: str | None 
    original_invoice_id: UUID | None 
    is_locked: bool 
    locked_at: datetime | None 
    voided_at: datetime | None
    voided_by: UUID | None
    void_reason: str | None
    created_at: datetime 
    updated_at: datetime 
    line_items: list[LineItemResponse]


class InvoiceVoidRequest(BaseModel):
    """
    Body for POST /invoices/{invoice_id}/void.

    void_reason is mandatory, same reasoning as PaymentCancelRequest.
    cancellation_reason — voiding is a permanent audit-trail entry
    (Invoice.invoice_status='void', voided_at/voided_by/void_reason all
    set, row never removed) and stating why is not optional for a
    financial document correction.
    """
    void_reason: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Why this invoice is being voided. Shown in the audit trail.",
    )


class InvoiceSummaryResponse(BaseModel):
    """
    One row of the invoice list. No line items (avoids a second query per
    row). outstanding_amount equals total_amount for drafts, so clients
    should only show it for non-draft statuses.
    """
    model_config = {"from_attributes": True}

    id: UUID
    invoice_number: str
    invoice_type: str
    invoice_date: date
    due_date: date | None
    party_id: UUID
    party_name: str | None = None
    party_gstin: str | None
    total_amount: Decimal
    paid_amount: Decimal
    outstanding_amount: Decimal
    refund_due_amount: Decimal
    invoice_status: InvoiceStatus
    created_at: datetime