from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enum import InvoiceStatus


class RefundCreateRequest(BaseModel):
    """POST /invoices/{invoice_id}/refunds. invoice_id comes from the path only."""
    refund_date: date = Field(..., description="Date the money was returned. Cannot be in the future.")
    amount: Decimal = Field(..., gt=0, le=Decimal("999999999999.99"), decimal_places=2,
                            description="Cash returned. Cannot exceed the refund due.", examples=["590.00"])
    refund_mode: str = Field(..., pattern=r"^(cash|bank_transfer|upi|cheque|credit_card)$", examples=["bank_transfer"])
    reference_number: str | None = Field(default=None, max_length=100, examples=["UTR998877"])
    bank_name: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("refund_date")
    @classmethod
    def refund_date_not_in_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError(f"Refund date {v} cannot be in the future.")
        return v

    @model_validator(mode="after")
    def reference_required_for_non_cash(self) -> "RefundCreateRequest":
        """Mirrors DB check_refund_reference_required_for_non_cash."""
        if self.refund_mode != "cash" and not self.reference_number:
            raise ValueError(f"refund_mode '{self.refund_mode}' requires reference_number.")
        return self


class RefundResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    refund_number: str
    invoice_id: UUID
    refund_date: date
    amount: Decimal
    refund_mode: str
    reference_number: str | None
    bank_name: str | None
    status: str
    created_at: datetime


class RefundRecordedResponse(BaseModel):
    """The refund plus the invoice's resulting ledger. Also the object cached for idempotent replay."""
    refund: RefundResponse
    invoice_id: UUID
    invoice_status: InvoiceStatus
    paid_amount: Decimal
    credited_amount: Decimal
    refunded_amount: Decimal
    outstanding_amount: Decimal
    refund_due_amount: Decimal


class RefundCancelRequest(BaseModel):
    """
    Body for POST /refunds/{refund_id}/cancel. A reason is mandatory for the audit trail.
    """
    cancellation_reason: str = Field(
        ..., min_length=5, max_length=500,
        description="Why this refund is being cancelled (for example: bank transfer bounced).",
        examples=["Bank transfer bounced"],
    )