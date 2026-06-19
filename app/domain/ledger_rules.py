from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Final, Literal


# Decimal ("0.01"): This tells exactly how many decimal places to keep. 
# By passing "0.01", you are instructing Python to strictly format the 
# number to two decimal places (e.g., 10.5 becomes 10.50). 
TWOPLACES: Final[Decimal] = Decimal("0.01")

# Decimal instances on every function call. At 1M invoice lines/day, creating
# Decimal("0.00") inside a loop adds measurable GC pressure.
ZERO: Final[Decimal] = Decimal("0.00")

# Maximum permitted rounding adjustment per GSTN invoicing rules.
# Adjustments beyond ±0.50 rupees are not rounding — they are errors.
MAX_ROUNDING_ADJUSTMENT: Final[Decimal] = Decimal("0.50")

# Only the draft invoice type is allowed to get modify
MUTABLE_STATES: frozenset[str] = frozenset({"draft"})

# Only if the invoice status is in sent and partial, 
# then only the payments will be accepted. 
PAYABLE_STATES: frozenset[str] = frozenset({"sent", "partial"})

InvoiceStatus = Literal[
    "draft",
    "sent",
    "partial",
    "paid",
    "overdue",
    "cancelled",
    "void",
]


# IMMUTABLE RESULT OBJECTS 
@dataclass(frozen=True)
class PaymentAllocationResult:
    """
    Complete ledger state after applying a new payment to an invoice. 
    """
    invoice_total: Decimal       # Immutable — the original invoice amount
    previously_paid: Decimal     # Total payments before this one
    new_payment: Decimal         # The payment being applied now
    total_paid_after: Decimal    # previously_paid + new_payment
    outstanding_after: Decimal   # invoice_total − total_paid_after (min 0)
    new_status: InvoiceStatus    # The status after this payment


@dataclass(frozen=True)
class InvoiceArithmeticReport: 
    """
    Result of validating an invoice's internal arithmetic consistency.
    """
    is_valid: bool
    expected_grand_total: Decimal   # Total computed server-side from line items
    declared_grand_total: Decimal   # Total submitted by the client
    discrepancy_amount: Decimal     # |expected − declared|


# HELPER FUNCTION
def _round(value: Decimal) -> Decimal:
    """
    Private monetary rounding. Single point of control for rounding method.
    """
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


#  ARITHMETIC VALIDATION 

def validate_invoice_arithmetic(
        line_item_totals: list[Decimal],
        declared_grand_total: Decimal,
        tolerance: Decimal = Decimal("0.02"),
)-> InvoiceArithmeticReport:
    """
    Verifies that the declared invoice grand total matches the sum of line totals.
    
    WHY VALIDATE ARITHMETIC IF WE COMPUTE TAXES OURSELVES?
    The invoice creation API accepts pre-computed line totals from the client
    (mobile app, accounting software, etc.). Client-side arithmetic may use
    JavaScript float, native platform float, or different rounding.
    This validation catches those discrepancies BEFORE any DB write.

    WHY A TOLERANCE PARAMETER?
    Per-line ROUND_HALF_UP rounding means the sum of rounded line totals can
    differ from rounding the unrounded aggregate by up to N * 0.005 rupees,
    where N = number of line items. Default tolerance of 0.02 comfortably
    covers up to 4-line invoices with single rounding events per line.
    The caller (service layer) may pass a higher tolerance for large invoices.
    """
    server_computed = _round(sum(line_item_totals,ZERO))
    discrepancy = _round(abs(server_computed - declared_grand_total))

    return InvoiceArithmeticReport(
        is_valid= discrepancy <= tolerance,
        expected_grand_total= server_computed,
        declared_grand_total= declared_grand_total,
        discrepancy_amount= discrepancy,
    )

# OUTSTANDING BALANCE 

def calculate_outstanding_balance(
    invoice_total: Decimal,
    total_payments_received: Decimal,
) -> Decimal:
    """
    Calculates the remaining unpaid balance on an invoice.
    WHY max(ZERO, ...)?
    Under normal operation, the service calls validate_payment_does_not_exceed_outstanding()
    before this function, ensuring total_payments_received never exceeds invoice_total.
    The max() provides a financial safety net for edge cases such as:
      - Floating point conversions from legacy data imports
      - Manual DB corrections by DBAs
      - Currency rounding from multi-currency future features
    A negative outstanding balance would corrupt the ledger.
    This guard makes that physically impossible regardless of input.
    """
    if total_payments_received > invoice_total:
        raise ValueError(
            f"Ledger Corruption: Total payments (₹{total_payments_received}) "
            f"exceed invoice total (₹{invoice_total})."
        )
    raw_balance = invoice_total - total_payments_received
    return _round(max(ZERO, raw_balance))


def validate_payment_does_not_exceed_outstanding(
    payment_amount: Decimal,
    current_outstanding: Decimal,
) -> None:
    """
    Raises ValueError if the payment would exceed the outstanding balance.

    WHY ValueError (not a GSTBillingException)?
    This is a pure domain function with zero knowledge of HTTP.
    The service layer catches ValueError and raises
    PaymentExceedsOutstandingError(payment=..., outstanding=...) which
    the global exception handler maps to HTTP 422.
    This preserves the clean architecture boundary: domain raises
    domain errors, the service translates them to application errors.
    """
    if payment_amount <= ZERO:
        raise ValueError(
            f"Payment amount must be greater than zero. "
            f"Received: ₹{payment_amount}"
        )
    if payment_amount > current_outstanding:
        raise ValueError(
            f"Payment ₹{payment_amount} exceeds "
            f"outstanding balance ₹{current_outstanding}."
        )


def allocate_payment(
    invoice_total: Decimal,
    previously_paid: Decimal,
    new_payment: Decimal,
) -> PaymentAllocationResult:
    """
    Applies a new payment to an invoice and returns the complete new ledger state.

    This is the single authoritative place where payment state transitions
    are computed. The payment_service calls this, then persists all returned
    values atomically inside a single `async with db.begin()` block.
    
    """
    current_outstanding = calculate_outstanding_balance(invoice_total, previously_paid)
    
    validate_payment_does_not_exceed_outstanding(new_payment, current_outstanding)
   
    total_paid_after  = _round(previously_paid + new_payment)
    outstanding_after = calculate_outstanding_balance(invoice_total, total_paid_after)

    new_status: InvoiceStatus = "paid" if outstanding_after == ZERO else "partial"

    return PaymentAllocationResult(
        invoice_total     = invoice_total,
        previously_paid   = previously_paid,
        new_payment       = new_payment,
        total_paid_after  = total_paid_after,
        outstanding_after = outstanding_after,
        new_status        = new_status,
    )


# INVOICE STATUS VALIDATION 

def validate_invoice_is_mutable(
    invoice_status: InvoiceStatus,
    invoice_number: str,
) -> None:
    """
    Raises ValueError if the invoice status prohibits modification.

    IMMUTABILITY RULE (CGST Act, 2017, Section 34):
    Once an invoice is submitted (moved from "draft"), it is a legal financial
    document. The GST Act does not permit post-submission modification of tax
    invoices. Corrections require a Credit Note or Debit Note to be issued.
    MUTABLE STATES:   {"draft"}
    IMMUTABLE STATES: {"sent", "partial", "paid", "void", "cancelled", "overdue"}
    """
    if invoice_status not in MUTABLE_STATES:
        raise ValueError(
            f"Invoice '{invoice_number}' is in status '{invoice_status}' "
            f"and cannot be modified. "
            f"Issue a Credit Note to correct a submitted invoice."
        )


def validate_invoice_accepts_payment(
    invoice_status: InvoiceStatus,
    invoice_number: str,
) -> None:
    """
    Raises ValueError if the invoice cannot accept a new payment.
    Payable States: {"sent", "partial"}
    """
    if invoice_status not in PAYABLE_STATES:
        raise ValueError(
            f"Invoice '{invoice_number}' is in status '{invoice_status}' "
            f"and cannot accept a payment. "
            f"Only 'sent' and 'partial' invoices accept payments."
        )

# CREDIT NOTE VALIDATION 

def validate_credit_note_amount(
    credit_note_amount: Decimal,
    original_invoice_total: Decimal,
    already_credited: Decimal = ZERO,
) -> None:
    """
    Raises ValueError if a credit note would exceed the creditable balance.

    STATUTORY RULE:
    A credit note can only reduce the buyer's liability up to the total value
    of the original invoice. You cannot credit more than what was invoiced —
    that would create a negative receivable, which is financially invalid
    and statutorily impermissible under the CGST Act.
    
    """
    creditable_balance = _round(original_invoice_total - already_credited)

    if credit_note_amount <= ZERO:
        raise ValueError(
            f"Credit note amount must be greater than zero. "
            f"Received: ₹{credit_note_amount}"
        )
    if credit_note_amount > creditable_balance:
        raise ValueError(
            f"Credit note ₹{credit_note_amount} exceeds "
            f"creditable balance ₹{creditable_balance} "
            f"(original ₹{original_invoice_total} − "
            f"already credited ₹{already_credited})."
        )
    
def calculate_post_credit_note_outstanding(
    original_invoice_total: Decimal,
    credit_note_amount: Decimal,
    amount_paid: Decimal = ZERO,
) -> Decimal:
    """
    Calculates the outstanding balance after applying a credit note.
    Example:
      Original invoice:   10,000
      Credit note:        2,000  (partial return)
      Adjusted invoice:   8,000
      Previously paid:    3,000
      Outstanding:        8,000 − 3,000 = 5,000

    """
    adjusted_invoice_total = _round(original_invoice_total - credit_note_amount)
    if amount_paid > adjusted_invoice_total:
        raise ValueError("amount paid should not be greater than actual pending invoice amount")
    return _round(max(ZERO, adjusted_invoice_total - amount_paid))