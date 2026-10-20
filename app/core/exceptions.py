from decimal import Decimal
from datetime import datetime 

class GSTBillingException(Exception):
    """
    Base class for all application errors and exceptions
    Every domain error inherits from this 

    message - human-readable description (shown to the user)
    code - machine-readable identifier (used by frontend to handle errors)
    status_code - the HTTP status code this maps to
    """
    def __init__(self, message: str, code: str, status_code: int = 400):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


# AUTHENTICATION EXCEPTIONS

class AuthenticationError(GSTBillingException):
    """
    Triggered when logins fails - email not found, password wrong, user inactive.
    DELIBERATELY vague message — do not tell the attacker which part failed.
    """
    def __init__(self) -> None:
        super().__init__("Invalid email or password.", "AUTHENTICATION_FAILED", 401)


class TokenExpiredError(GSTBillingException):
    """Triggered when a user tries to use an access token that is older than 15 minutes."""
    def __init__(self) -> None:
        super().__init__("Token has expired.", "TOKEN_EXPIRED", 401)


class TokenInvalidError(GSTBillingException):
    """
    Triggered when a token's cryptographic signature is fake, or if someone
    tries to use a 7-day refresh token in a place that requires a 15-minute access token.
    """
    def __init__(self) -> None:
        super().__init__("Token is invalid.", "TOKEN_INVALID", 401)


class RefreshTokenRevokedError(GSTBillingException):
    """
    Triggered when a user clicks 'Logout', but later tries to use that
    same old session to get a new access token.
    """
    def __init__(self) -> None:
        super().__init__("Session has been revoked.", "TOKEN_REVOKED", 401)


# REGISTRATION EXCEPTIONS (used during POST/auth/register)

class DuplicateGSTINError(GSTBillingException):
    """Triggered during registration if a business tries to sign up with a GSTIN already in use."""
    def __init__(self, gstin: str) -> None:
        super().__init__(f"GSTIN '{gstin}' is already registered.", "DUPLICATE_GSTIN", 409)

class DuplicatePANError(GSTBillingException):
    """
    A tenant with this PAN already exists (uq_tenant_pan). The platform
    supports one tenant per PAN, so a second GSTIN under the same PAN
    (for example a branch in another state) is rejected.
    """
    def __init__(self, pan:str) -> None:
        super().__init__(f"Pan '{pan}' is already registered under another GSTIN.", 
                        "DUPLICATE_PAN", 409
                        )


class DuplicateComplianceProfileError(GSTBillingException):
    """
    A compliance profile already exists for this (tenant, financial_year).
    Raised before the DB UniqueConstraint fires — returns a clean 409
    instead of a raw IntegrityError 500.
    """
    def __init__(self, financial_year: str) -> None:
        super().__init__(
            f"A compliance profile for financial year '{financial_year}' already exists.",
            "COMPLIANCE_DUPLICATE",
            409,
        )


class StateCodeMismatchError(GSTBillingException):
    """
    The first two digits of the GSTIN are the state code of registration.
    A different state_code in the request would make every future invoice
    classify supplies as intrastate or interstate incorrectly.
    """
    def __init__(self, gstin: str, state_code: str) -> None:
        super().__init__(
            f"GSTIN '{gstin}' belongs to state code '{gstin[:2]}', "
            f"but state_code '{state_code}' was supplied.",
            "STATE_CODE_MISMATCH",
            422,
        )

# USER EXCEPTIONS

class DuplicateEmailError(GSTBillingException):
    """Triggered during registration or user creation if the email already exists within that business."""
    def __init__(self, email: str) -> None:
        super().__init__(f"Email '{email}' is already registered.", "DUPLICATE_EMAIL", 409)


class UserInactiveError(GSTBillingException):
    """Triggered during login if the business owner has manually blocked or fired this employee."""
    def __init__(self) -> None:
        super().__init__("Account is deactivated. Contact your administrator.", "USER_INACTIVE", 403)


class PermissionDeniedError(GSTBillingException):
    """
    Authenticated user's role does not permit the requested action.
    Raised by require_role() in core/dependencies.py.
    HTTP 403 — identity is known, permission is denied.
    """
    def __init__(self, role: str, action: str) -> None:
        super().__init__(f"Role '{role}' is not permitted to perform '{action}'.", "PERMISSION_DENIED", 403)


# INVOICE EXCEPTIONS

class InvoiceNotFoundError(GSTBillingException):
    """
    Invoice does not exist OR belongs to a different tenant.
    404 for both cases — deliberately, to avoid leaking existence of another
    tenant's invoice via a 403.
    """
    def __init__(self, identifier: str) -> None:
        super().__init__(f"Invoice '{identifier}' not found.", "INVOICE_NOT_FOUND", 404)


class OriginalInvoiceNotFoundError(GSTBillingException):
    """The original_invoice_id referenced by a credit/debit note does not exist."""
    def __init__(self, identifier: str) -> None:
        super().__init__(f"Original invoice '{identifier}' not found.", "ORIGINAL_INVOICE_NOT_FOUND", 404)


class InvoiceLockedError(GSTBillingException):
    """
    Attempted mutation on an invoice whose status forbids it
    (ledger_rules.validate_invoice_is_mutable / void preconditions).
    """
    def __init__(self, message: str) -> None:
        super().__init__(message, "INVOICE_LOCKED", 409)


class InvoiceNotPayableError(GSTBillingException):
    """Invoice status is not in ledger_rules.PAYABLE_STATES."""
    def __init__(self, invoice_number: str, current_status: str) -> None:
        super().__init__(
            f"Invoice '{invoice_number}' is in status '{current_status}' and cannot accept a payment.",
            "INVOICE_NOT_PAYABLE",
            422,
        )


class InvoiceAlreadyPaidError(GSTBillingException):
    """Invoice's outstanding_amount is already zero — nothing left to pay."""
    def __init__(self, invoice_number: str) -> None:
        super().__init__(f"Invoice '{invoice_number}' is already fully paid.", "INVOICE_ALREADY_PAID", 422)


class PaymentExceedsOutstandingError(GSTBillingException):
    """Payment amount exceeds the invoice's current outstanding balance."""
    def __init__(self, payment_amount: Decimal, outstanding_amount: Decimal, invoice_number: str) -> None:
        super().__init__(
            f"Payment ₹{payment_amount} exceeds outstanding balance ₹{outstanding_amount} "
            f"on invoice '{invoice_number}'.",
            "PAYMENT_EXCEEDS_OUTSTANDING",
            422,
        )


class PaymentNotFoundError(GSTBillingException):
    """Payment does not exist in the database."""
    def __init__(self, identifier: str) -> None:
        super().__init__(f"Payment '{identifier}' not found.", "PAYMENT_NOT_FOUND", 404)


class InvalidGSTRateError(GSTBillingException):
    """GST rate is not in tax_engine.GST_RATE_SLABS."""
    def __init__(self, message: str) -> None:
        super().__init__(message, "GST_RATE_INVALID", 422)


class InvalidHSNCodeError(GSTBillingException):
    """HSN/SAC code fails business_rules.validate_hsn_code()."""
    def __init__(self, message: str) -> None:
        super().__init__(message, "HSN_CODE_INVALID", 422)


class InvalidInvoiceNumberError(GSTBillingException):
    """Invoice number fails business_rules.validate_invoice_number_format()."""
    def __init__(self, invoice_number: str) -> None:
        super().__init__(f"Invoice number '{invoice_number}' has an invalid format.", "INVOICE_NUMBER_INVALID", 422)


class InvoiceArithmeticError(GSTBillingException):
    """Client-declared grand total does not match server-computed total within tolerance."""
    def __init__(self, expected, declared, discrepancy) -> None:
        super().__init__(
            f"Invoice total mismatch: expected ₹{expected}, received ₹{declared} "
            f"(discrepancy ₹{discrepancy}).",
            "INVOICE_ARITHMETIC_MISMATCH",
            422,
        )


class CreditNoteExceedsInvoiceError(GSTBillingException):
    """Credit note amount exceeds the creditable balance on the original invoice."""
    def __init__(self, message: str) -> None:
        super().__init__(message, "CREDIT_NOTE_EXCEEDS_INVOICE", 422)


# PAYMENTS MANAGEMENT — idempotency & duplicate handling

class DuplicateRequestInProgressError(GSTBillingException):
    def __init__(self, idempotency_key: str) -> None:
        super().__init__(
            (
                f"A request with Idempotency-Key '{idempotency_key}' is already being "
                f"processed or was very recently completed. Do not resubmit; check the "
                f"result of the original request instead."
            ),
            "DUPLICATE_REQUEST_IN_PROGRESS",
            409,
        )


class PaymentReferenceAlreadyUsedError(GSTBillingException):
    def __init__(self, reference_number: str, existing_payment_number: str) -> None:
        super().__init__(
            (
                f"Reference number '{reference_number}' is already recorded against "
                f"payment '{existing_payment_number}' for this tenant. A bank/UPI/cheque "
                f"reference can only be recorded once."
            ),
            "PAYMENT_REFERENCE_ALREADY_USED",
            409,
        )


class PossibleDuplicatePaymentError(GSTBillingException):
    def __init__(self, invoice_number: str, amount: Decimal, existing_payment_number: str, elapsed_display: str) -> None:
        super().__init__(
            (
                f"A payment of ₹{amount} was already recorded against invoice "
                f"'{invoice_number}' {elapsed_display} ago (receipt "
                f"'{existing_payment_number}'). If this is genuinely a separate payment, "
                f"resubmit the request with confirm_duplicate=true."
            ),
            "POSSIBLE_DUPLICATE_PAYMENT",
            422,
        )


class IdempotencyKeyReusedWithDifferentPayloadError(GSTBillingException):
    def __init__(self, idempotency_key: str) -> None:
        super().__init__(
            (
                f"Idempotency-Key '{idempotency_key}' was already used for a request with "
                f"different parameters. An idempotency key must uniquely identify ONE "
                f"specific request — generate a new key for a genuinely different operation."
            ),
            "IDEMPOTENCY_KEY_PAYLOAD_MISMATCH",
            409,
        )


class PaymentAlreadyCancelledError(GSTBillingException):
    """
    Raised when cancel_payment() targets a payment already in
    status='cancelled' — either the fast-path check before the invoice
    lock, or the rowcount check on soft_cancel_by_id() inside it (see
    payment_repository.soft_cancel_by_id docstring for why the latter
    exists: a payment can lose a race and be cancelled by a concurrent
    request between this request's read and its own attempt to cancel).

    409, not 404 — the payment exists and the request is well-formed;
    its current state conflicts with the requested operation. 404 would
    hide that the payment exists, which is the wrong signal for an
    accountant who double-clicked "Cancel" and deserves "already
    cancelled", not "not found".

    409, not 422 — 422 is for malformed requests (bad amount, future
    date). This is a state conflict, not a validation failure.
    """
    def __init__(self, payment_id: str, payment_number: str, cancelled_at: "datetime | None") -> None:
        cancelled_str = (
            cancelled_at.strftime("%d-%b-%Y %H:%M UTC")
            if cancelled_at
            else "unknown time"
        )
        super().__init__(
            f"Payment '{payment_number}' (id: {payment_id}) has already been "
            f"cancelled at {cancelled_str}. A cancelled payment cannot be "
            f"cancelled again.",
            "PAYMENT_ALREADY_CANCELLED",
            409,
        )


class InvoiceNotVoidableError(GSTBillingException):
    """
    Raised when void_invoice() targets an invoice that fails
    ledger_rules.validate_invoice_is_voidable — either its invoice_status
    is not "sent" (draft was never issued; partial/paid/void/cancelled/
    overdue can't be voided) or it has non-zero paid_amount (money already
    received requires a Credit Note, not a void — see the domain function's
    docstring for why voiding a paid invoice would orphan real payments).

    422, matching InvoiceNotPayableError's precedent in this file — this is
    a business-rule rejection on a well-formed request, not a 409 state
    conflict like PaymentAlreadyCancelledError. The distinction: void isn't
    idempotent by nature the way cancel is (there's no "already voided,
    try again" race this guards against) — it's a straightforward "this
    invoice's current state doesn't qualify" rejection, same shape as
    trying to pay an invoice that isn't in a payable state.
    """
    def __init__(self, invoice_number: str, current_status: str, paid_amount: Decimal) -> None:
        super().__init__(
            f"Invoice '{invoice_number}' (status: '{current_status}', paid: ₹{paid_amount}) "
            f"cannot be voided. Only 'sent' invoices with no payments recorded "
            f"can be voided. Issue a Credit Note to correct an invoice with "
            f"payments already applied.",
            "INVOICE_NOT_VOIDABLE",
            422,
        )


class PartyTypeMismatchError(GSTBillingException):
    """
    Party exists but its party_type doesn't match what this operation
    requires (e.g. invoicing a vendor-only party on a sales invoice).
    Distinct from PartyNotFoundError — the party is real, the request
    just targeted it incorrectly. 422, not 404: the request is
    well-formed, the party reference is valid, but the combination is
    semantically wrong.
    """
    def __init__(self, party_id: str, required_type: str) -> None:
        super().__init__(
            f"Party '{party_id}' exists but is not a valid '{required_type}' "
            f"for this operation.",
            "PARTY_TYPE_MISMATCH",
            422,
        )


class CreditNotePartyMismatchError(GSTBillingException):
    """
    A credit note's party_id must match the original invoice's party_id —
    a credit note is a correction to a specific transaction with a
    specific customer; it cannot reassign that adjustment to a different
    party. Distinct from CreditNoteExceedsInvoiceError (an amount problem)
    and OriginalInvoiceNotFoundError (a reference problem) — this is an
    identity mismatch between the two documents.
    """
    def __init__(self, original_invoice_number: str, original_party_id: str, request_party_id: str) -> None:
        super().__init__(
            f"Credit note party '{request_party_id}' does not match original "
            f"invoice '{original_invoice_number}''s party '{original_party_id}'. "
            f"A credit note must be issued to the same party as the invoice it corrects.",
            "CREDIT_NOTE_PARTY_MISMATCH",
            422,
        )


class PossibleDuplicateInvoiceError(GSTBillingException):
    def __init__(self, party_id: str, amount: Decimal, existing_invoice_number: str, elapsed_display: str) -> None:
        super().__init__(
            f"An invoice of ₹{amount} for this party was already created "
            f"{elapsed_display} ago (invoice '{existing_invoice_number}'). "
            f"If this is genuinely a separate invoice, resubmit with confirm_duplicate=true.",
            "POSSIBLE_DUPLICATE_INVOICE", 422,
        )


class DuplicateCreditNoteError(GSTBillingException):
    """Hard block — no override. A duplicate credit note double-reduces real revenue and GST liability."""
    def __init__(self, original_invoice_number: str, amount: Decimal, existing_credit_note_number: str) -> None:
        super().__init__(
            f"A credit note of ₹{amount} against invoice '{original_invoice_number}' "
            f"already exists ('{existing_credit_note_number}'). Credit notes cannot be duplicated.",
            "DUPLICATE_CREDIT_NOTE", 409,
        )


class InvoiceNotCreditableError(GSTBillingException):
    """
    Raised when a credit note targets an original invoice that fails
    ledger_rules.validate_invoice_accepts_credit_note: the original is not
    a sales/purchase invoice, or it is not in a payable state ('sent' or
    'partial'). Used at credit note creation AND again at submission, since
    the original's state can change between the two.

    422, same precedent as InvoiceNotPayableError and InvoiceNotVoidableError:
    a business-rule rejection of a well-formed request, not a state conflict
    from a race. The message comes from the domain function and already
    names the invoice and the reason.
    """
    def __init__(self, message: str) -> None:
        super().__init__(message, "INVOICE_NOT_CREDITABLE", 422)


class PartyInactiveError(GSTBillingException):
    """
    Raised when an invoice is created for a deactivated party
    (Party.is_active = False). The party exists and the type is correct, so
    this is not a PartyNotFound or PartyTypeMismatch case. 422, same family
    as PartyTypeMismatchError. The fix is on the user's side: reactivate
    the party or pick a different one.
    """
    def __init__(self, party_id: str) -> None:
        super().__init__(
            f"Party '{party_id}' is deactivated and cannot be used on new invoices. "
            f"Reactivate the party first, or choose a different one.",
            "PARTY_INACTIVE",
            422,
        )


class PartyNotFoundError(GSTBillingException):
    """
    Party does not exist OR belongs to a different tenant. 404 for both,
    deliberately, to avoid leaking another tenant's party ids.
    """
    def __init__(self, identifier: str) -> None:
        super().__init__(f"Party '{identifier}' not found.", "PARTY_NOT_FOUND", 404)


class TenantNotFoundError(GSTBillingException):
    """
    The tenant_id from a valid token has no tenant row. Should be
    unreachable in normal operation, so this signals data corruption or a
    deleted tenant with a live token.
    """
    def __init__(self, identifier: str) -> None:
        super().__init__(f"Tenant '{identifier}' not found.", "TENANT_NOT_FOUND", 404)


class DuplicatePartyGSTINError(GSTBillingException):
    """A party with this GSTIN already exists for this tenant (uq_party_tenant_gstin)."""
    def __init__(self, gstin: str) -> None:
        super().__init__(
            f"A party with GSTIN '{gstin}' already exists.",
            "DUPLICATE_PARTY_GSTIN",
            409,
        )


class InvalidPartyTaxIdentityError(GSTBillingException):
    """GSTIN format invalid, GSTIN state does not match state_code, or PAN does not match GSTIN."""
    def __init__(self, message: str) -> None:
        super().__init__(message, "PARTY_TAX_IDENTITY_INVALID", 422)


class InvalidListQueryError(GSTBillingException):
    """Bad cursor or inconsistent list filters (for example date_from after date_to)."""
    def __init__(self, message: str) -> None:
        super().__init__(message, "INVALID_LIST_QUERY", 422)


class RefundExceedsDueError(GSTBillingException):
    """Refund amount is more than the seller currently owes the customer on this invoice."""
    def __init__(self, amount: Decimal, refund_due: Decimal, invoice_number: str) -> None:
        super().__init__(
            f"Refund ₹{amount} exceeds the refund due ₹{refund_due} on invoice '{invoice_number}'.",
            "REFUND_EXCEEDS_DUE", 422,
        )


class RefundReferenceAlreadyUsedError(GSTBillingException):
    def __init__(self, reference_number: str) -> None:
        super().__init__(
            f"Refund reference '{reference_number}' is already recorded for this tenant.",
            "REFUND_REFERENCE_ALREADY_USED", 409,
        )


class PaymentCancelBlockedByRefundError(GSTBillingException):
    """Cancelling this payment would leave more cash refunded than received."""
    def __init__(self, invoice_number: str) -> None:
        super().__init__(
            f"This payment cannot be cancelled: refunds already paid on invoice "
            f"'{invoice_number}' exceed the cash that would remain. Reverse the refund first.",
            "PAYMENT_CANCEL_BLOCKED_BY_REFUND", 409,
        )


class RefundNotFoundError(GSTBillingException):
    """Refund does not exist OR belongs to a different tenant (404 for both)."""
    def __init__(self, identifier: str) -> None:
        super().__init__(f"Refund '{identifier}' not found.", "REFUND_NOT_FOUND", 404)


class RefundAlreadyCancelledError(GSTBillingException):
    """409: the refund exists but is already cancelled (state conflict, not a bad request)."""
    def __init__(self, refund_id: str, refund_number: str, cancelled_at: "datetime | None") -> None:
        cancelled_str = (
            cancelled_at.strftime("%d-%b-%Y %H:%M UTC") if cancelled_at else "unknown time"
        )
        super().__init__(
            f"Refund '{refund_number}' (id: {refund_id}) has already been cancelled at "
            f"{cancelled_str}.",
            "REFUND_ALREADY_CANCELLED",
            409,
        )