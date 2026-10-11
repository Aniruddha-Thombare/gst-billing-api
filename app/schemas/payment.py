from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enum import InvoiceStatus

# Modes with a natural uniqueness key (UTR / UPI ref / cheque number).
# Enforced by the hard DB constraint uq_payments_tenant_refnum.
# credit_card also requires a reference (see validate_reference_number_for_non_cash)
# but has no hard uniqueness check; it gets the soft duplicate check instead.
REFERENCE_REQUIRED_MODES = frozenset({"bank_transfer", "upi", "cheque"})


class PaymentCreateRequest(BaseModel):
    """
    POST /api/v1/invoices/{invoice_id}/payments

    invoice_id is intentionally NOT a field here: it comes exclusively from
    the URL path, so the client cannot send conflicting values.

    amount: gt=0 (a zero payment is a no-op) and le=999999999999.99, which
    fits the Numeric(17,2) column.

    payment_mode: the regex is the canonical list of accepted modes. A new
    mode must be added here AND to the DB check constraint.
    """

    payment_date: date = Field(
        ...,
        description="Date the payment was received. Cannot be in the future.",
    )
    amount: Decimal = Field(
        ...,
        gt=0,
        le=Decimal("999999999999.99"),
        decimal_places=2,
        description="Amount received. Must be positive. Cannot exceed invoice outstanding.",
    )
    payment_mode: str = Field(
        ...,
        pattern=r"^(cash|bank_transfer|upi|cheque|credit_card)$",
        description="Mode of payment. Must be one of the allowed modes.",
    )
    reference_number: str | None = Field(
        default=None,
        max_length=100,
        description="External reference: NEFT transaction ID, UPI ref, cheque number.",
    )
    bank_name: str | None = Field(
        default=None,
        max_length=100,
        description="Bank name. Required for cheque/bank_transfer modes.",
    )
    notes: str | None = Field(
        default=None,
        max_length=1000,
        description="Internal note. Visible to all roles. Not sent to customer.",
    )
    confirm_duplicate: bool = Field(
        default=False,
        description=(
            "Set true only when re-submitting a cash/credit_card payment that the API "
            "flagged as a possible duplicate (422 POSSIBLE_DUPLICATE_PAYMENT), "
            "after confirming it is a genuinely separate payment. "
            "Ignored for reference-numbered modes, which use a hard uniqueness check."
        ),
    )

    @field_validator("payment_date")
    @classmethod
    def payment_date_not_in_future(cls, v: date) -> date:
        """Money cannot be received in the future. Fails fast, before any DB lock."""
        if v > date.today():
            raise ValueError(
                f"Payment date {v} cannot be in the future. Today is {date.today()}."
            )
        return v

    @model_validator(mode="after")
    def validate_bank_name_for_cheque_and_transfer(self) -> "PaymentCreateRequest":
        """
        Mirrors DB check_payment_bank_name_required_for_bank_cheque, so the
        client gets a clean 422 instead of a raw IntegrityError.
        """
        if self.payment_mode in ("cheque", "bank_transfer") and not self.bank_name:
            raise ValueError(f"payment_mode '{self.payment_mode}' requires bank_name.")
        return self

    @model_validator(mode="after")
    def validate_reference_number_for_non_cash(self) -> "PaymentCreateRequest":
        """
        Mirrors DB check_payment_reference_required_for_non_cash: every mode
        except cash needs a reference (reconciliation and duplicate detection).
        """
        if self.payment_mode != "cash" and not self.reference_number:
            raise ValueError(
                f"payment_mode '{self.payment_mode}' requires reference_number."
            )
        return self


class PaymentResponse(BaseModel):
    """One payment as returned by the API (includes status, since cancelled payments are kept)."""
    model_config = {"from_attributes": True}

    id: UUID
    payment_number: str
    invoice_id: UUID
    payment_date: date
    amount: Decimal
    payment_mode: str
    reference_number: str | None
    bank_name: str | None
    status: str
    created_at: datetime


class PaymentRecordedResponse(BaseModel):
    """
    Response for POST /invoices/{invoice_id}/payments.

    Returns BOTH the new payment and the resulting invoice ledger state, so
    the client updates its UI without a second round trip. This is also the
    exact object cached and replayed by idempotency_service, so its shape
    must be reconstructable from JSON.
    """
    model_config = {"from_attributes": True}

    payment: PaymentResponse
    invoice_id: UUID
    invoice_status: InvoiceStatus
    paid_amount: Decimal
    outstanding_amount: Decimal


class PaymentCancelRequest(BaseModel):
    """
    Body for the payment cancel endpoint (soft-cancel; nothing is ever
    hard-deleted). cancellation_reason is mandatory: a cancelled payment is
    a permanent audit-trail entry and must state why.
    """
    cancellation_reason: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Why this payment is being cancelled. Shown in the audit trail.",
    )