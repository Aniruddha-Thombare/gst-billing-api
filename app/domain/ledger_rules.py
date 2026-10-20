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

# Only invoices in "sent" status are voidable — a draft was never issued,
# there's nothing to void (it can simply stay a draft or be discarded);
# "partial"/"paid" mean money has already been received, which void
# cannot represent correctly (see validate_invoice_is_voidable below,
# which also independently checks paid_amount == 0 as a second guard —
# same defense-in-depth pattern as PAYABLE_STATES + the outstanding check).
VOIDABLE_STATES: frozenset[str] = frozenset({"sent"})

# A credit note may be issued against any submitted invoice, including a fully
# paid one (the customer is then owed a refund). Draft and void never qualify.
CREDITABLE_STATES: frozenset[str] = frozenset({"sent", "partial", "paid"})

# Only sales and purchase invoices can be corrected by a credit note.
# Crediting a credit note, a debit note or a payment receipt has no
# meaning under the CGST Act, so the original's type is its own guard,
# independent of its status.
CREDITABLE_ORIGINAL_TYPES: frozenset[str] = frozenset({"sales", "purchase"})

InvoiceStatus = Literal[
    "draft",
    "sent",
    "partial",
    "paid",
    "overdue",
    "cancelled",
    "void",
]

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

@dataclass(frozen=True)
class LedgerPosition:
    """
    The full money position of one invoice, derived from its four components.
      outstanding_amount: what the customer still owes the seller
      refund_due_amount:  what the seller still owes the customer
    At most one of the two is non-zero.
    """
    invoice_total: Decimal
    paid_amount: Decimal        # cash received
    credited_amount: Decimal    # credit notes applied
    refunded_amount: Decimal    # cash returned
    outstanding_amount: Decimal
    refund_due_amount: Decimal
    status: InvoiceStatus


def compute_ledger_position(
    *,
    invoice_total: Decimal,
    paid_amount: Decimal,
    credited_amount: Decimal,
    refunded_amount: Decimal,
) -> LedgerPosition:
    """
    Single authoritative ledger formula, used by record payment, cancel
    payment, send credit note and record refund. Pure, no DB access.

        balance = total - credits - cash paid + refunds
        balance > 0 -> customer owes it;  balance < 0 -> seller owes a refund.

    Status: 'paid' when balance <= 0 and anything was paid or credited;
    'partial' when something was paid (net of refunds) or credited; else 'sent'.
    Raises ValueError if the components are impossible (ledger corruption).
    """
    if min(paid_amount, credited_amount, refunded_amount) < ZERO:
        raise ValueError("Ledger corruption: negative ledger component.")
    if credited_amount > invoice_total:
        raise ValueError(
            f"Ledger corruption: credits ₹{credited_amount} exceed invoice total ₹{invoice_total}."
        )
    if refunded_amount > paid_amount:
        raise ValueError(
            f"Ledger corruption: refunds ₹{refunded_amount} exceed cash received ₹{paid_amount}."
        )

    balance = _round(invoice_total - credited_amount - paid_amount + refunded_amount)
    outstanding = max(balance, ZERO)
    refund_due = max(-balance, ZERO)

    if balance <= ZERO and (paid_amount > ZERO or credited_amount > ZERO):
        status: InvoiceStatus = "paid"
    elif (paid_amount - refunded_amount) > ZERO or credited_amount > ZERO:
        status = "partial"
    else:
        status = "sent"

    return LedgerPosition(
        invoice_total=invoice_total, paid_amount=paid_amount,
        credited_amount=credited_amount, refunded_amount=refunded_amount,
        outstanding_amount=outstanding, refund_due_amount=refund_due, status=status,
    )


def apply_payment(
    *, invoice_total: Decimal, paid_amount: Decimal, credited_amount: Decimal,
    refunded_amount: Decimal, new_payment: Decimal,
) -> LedgerPosition:
    """Ledger position after receiving a payment. ValueError if it exceeds the outstanding balance."""
    current = compute_ledger_position(
        invoice_total=invoice_total, paid_amount=paid_amount,
        credited_amount=credited_amount, refunded_amount=refunded_amount,
    )
    validate_payment_does_not_exceed_outstanding(new_payment, current.outstanding_amount)
    return compute_ledger_position(
        invoice_total=invoice_total, paid_amount=_round(paid_amount + new_payment),
        credited_amount=credited_amount, refunded_amount=refunded_amount,
    )


def apply_credit_note(
    *, invoice_total: Decimal, paid_amount: Decimal, credited_amount: Decimal,
    refunded_amount: Decimal, credit_amount: Decimal,
) -> LedgerPosition:
    """
    Ledger position after applying a credit note. Works on a fully paid
    invoice too (it then creates a refund due). Total credits can never
    exceed the invoice total.
    """
    if credit_amount <= ZERO:
        raise ValueError(f"Credit note amount must be greater than zero. Received: ₹{credit_amount}")
    new_credited = _round(credited_amount + credit_amount)
    if new_credited > invoice_total:
        raise ValueError(
            f"Credit ₹{credit_amount} would take total credits to ₹{new_credited}, "
            f"above the invoice total ₹{invoice_total}."
        )
    return compute_ledger_position(
        invoice_total=invoice_total, paid_amount=paid_amount,
        credited_amount=new_credited, refunded_amount=refunded_amount,
    )


def apply_refund(
    *, invoice_total: Decimal, paid_amount: Decimal, credited_amount: Decimal,
    refunded_amount: Decimal, refund_amount: Decimal,
) -> LedgerPosition:
    """Ledger position after paying a refund. ValueError if it exceeds the refund due."""
    if refund_amount <= ZERO:
        raise ValueError(f"Refund amount must be greater than zero. Received: ₹{refund_amount}")
    current = compute_ledger_position(
        invoice_total=invoice_total, paid_amount=paid_amount,
        credited_amount=credited_amount, refunded_amount=refunded_amount,
    )
    if refund_amount > current.refund_due_amount:
        raise ValueError(
            f"Refund ₹{refund_amount} exceeds the refund due ₹{current.refund_due_amount}."
        )
    return compute_ledger_position(
        invoice_total=invoice_total, paid_amount=paid_amount,
        credited_amount=credited_amount, refunded_amount=_round(refunded_amount + refund_amount),
    )


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

def validate_invoice_accepts_credit_note(
    original_invoice_type: str,
    original_invoice_status: InvoiceStatus,
    original_invoice_number: str,
) -> None:
    """
    Raises ValueError if a credit note cannot be issued against this invoice.

    Two independent guards, both must pass:
    1. The original must be a sales or purchase invoice, not itself a
       credit note or debit note.
    2. The original must be submitted (‘sent’, ‘partial’ or ‘paid’). 
    A fully paid invoice is allowed: the credit then creates a refund due.
    """
    if original_invoice_type not in CREDITABLE_ORIGINAL_TYPES:
        raise ValueError(
            f"Invoice '{original_invoice_number}' is a '{original_invoice_type}' and "
            f"cannot be credited. Credit notes can only be issued against sales "
            f"or purchase invoices."
        )
    if original_invoice_status not in CREDITABLE_STATES:
        raise ValueError(
            f"Invoice '{original_invoice_number}' is in status '{original_invoice_status}' "
            f"and cannot receive a credit note. Only submitted invoices "
            f"('sent', 'partial' or 'paid') can be credited."
        )
    

def validate_invoice_is_voidable(
    invoice_status: InvoiceStatus,
    paid_amount: Decimal,
    invoice_number: str,
    invoice_type: str
) -> None:
    """
    Raises ValueError if the invoice cannot be voided.

    Two independent guards, both must pass:
    1. invoice_status must be "sent" — draft was never issued (nothing to
       void); partial/paid/void/cancelled/overdue are all terminal or
       payment-bearing states void cannot represent.
    2. paid_amount must be exactly zero — this is the real invariant.
       VOIDABLE_STATES alone would already exclude "partial"/"paid" by
       name, but checking paid_amount directly guards against the status
       and the amount ever drifting apart 

    Voiding an invoice with real payments recorded against it would leave
    those payments orphaned with nothing valid to point to — the correct
    instrument for a submitted, paid invoice needing correction is a
    Credit Note, not a void.
    """
    if invoice_type == "credit_note":
        raise ValueError(f"Credit note '{invoice_number}' cannot be voided once sent")

    if invoice_status not in VOIDABLE_STATES:
        raise ValueError(
            f"Invoice '{invoice_number}' is in status '{invoice_status}' "
            f"and cannot be voided. Only 'sent' invoices with no payments "
            f"recorded can be voided."
        )
    if paid_amount != ZERO:
        raise ValueError(
            f"Invoice '{invoice_number}' has ₹{paid_amount} in recorded "
            f"payments and cannot be voided. Issue a Credit Note instead."
        )