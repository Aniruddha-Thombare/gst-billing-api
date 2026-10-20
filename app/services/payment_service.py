from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from uuid import UUID
from datetime import datetime, timezone, date 

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import idempotency_service
from app.repositories import invoice_repository, payment_repository, refund_repository
from app.services import sequence_service
from app.domain import ledger_rules
from app.schemas.payment import (
    REFERENCE_REQUIRED_MODES, PaymentCreateRequest, PaymentResponse, 
    PaymentRecordedResponse
)
from app.core.db_errors import get_constraint_name
from app.core.pagination import Page, encode_cursor, decode_date_cursor
from app.core.exceptions import (
    InvoiceNotFoundError, InvoiceNotPayableError, InvoiceAlreadyPaidError,
    PaymentExceedsOutstandingError, PaymentReferenceAlreadyUsedError,
    PossibleDuplicatePaymentError, PaymentNotFoundError, PaymentAlreadyCancelledError,
    InvalidListQueryError, PaymentCancelBlockedByRefundError
)

_MAX_SEQUENCE_RETRIES = 1

CASH_CARD_DUPLICATE_WINDOW_MINUTES = 24 * 60


def compute_request_fingerprint(*, invoice_id: UUID, request: PaymentCreateRequest) -> str:
    """
    Business-relevant fingerprint of a payment request, deliberately NOT
    a hash of the raw JSON body. Excludes `notes` and `confirm_duplicate`.
    """
    payload = {
        "invoice_id": str(invoice_id),
        "amount": str(request.amount),
        "payment_mode": request.payment_mode,
        "reference_number": request.reference_number,
        "payment_date": request.payment_date.isoformat(),
        "bank_name": request.bank_name,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def record_payment(
    db: AsyncSession, *, tenant_id: UUID, user_id: UUID, invoice_id: UUID,
    request: PaymentCreateRequest, idempotency_key: str,
) -> PaymentRecordedResponse:
    """
    Idempotency-Key is mandatory for this endpoint (enforced at the router
    as a required header).
    """
    return await _record_payment_idempotent(
        db, tenant_id=tenant_id, user_id=user_id, invoice_id=invoice_id,
        request=request, idempotency_key=idempotency_key, retry_count=0,
    )


def _enqueue_payment_recorded_tasks(*, payment_id: str, tenant_id: str) -> None:
    """
    Fires background work (receipt email, AR cache invalidation) AFTER the
    caller's transaction has already committed. Stub for now: replace with
    real Celery task dispatch once background task infra is built.
    """
    pass


async def _record_payment_idempotent(
    db: AsyncSession, *, tenant_id: UUID, user_id: UUID, invoice_id: UUID,
    request: PaymentCreateRequest, idempotency_key: str, retry_count: int,
) -> PaymentRecordedResponse:
    """
    Owns the transaction of the entire payment recording: idempotency
    reservation + payment body + completion, all in one atomic transaction.
    """
    request_hash = compute_request_fingerprint(invoice_id=invoice_id, request=request)

    try:
        async with db.begin():
            outcome = await idempotency_service.try_reserve(
                db, tenant_id=tenant_id, endpoint="record_payment",
                idempotency_key=idempotency_key, request_hash=request_hash,
            )
            if outcome.is_replay:
                return PaymentRecordedResponse.model_validate_json(outcome.cached_response)

            response = await _record_payment_body(
                db, tenant_id=tenant_id, user_id=user_id, invoice_id=invoice_id, request=request,
            )

            await idempotency_service.mark_completed_in_open_txn(
                db, tenant_id=tenant_id, row_id=outcome.row_id,
                response_json=response.model_dump_json(),
            )
    except IntegrityError as exc:
        return await _retry_or_raise(
            db, exc, tenant_id=tenant_id, user_id=user_id, invoice_id=invoice_id,
            request=request, idempotency_key=idempotency_key, retry_count=retry_count,
        )

    _enqueue_payment_recorded_tasks(payment_id=str(response.payment.id), tenant_id=str(tenant_id))
    return response


async def _retry_or_raise(
    db: AsyncSession, exc: IntegrityError, *, tenant_id: UUID, user_id: UUID,
    invoice_id: UUID, request: PaymentCreateRequest, idempotency_key: str, retry_count: int,
) -> PaymentRecordedResponse:
    """
    Routes an IntegrityError by constraint name, never a catch-all retry:
    - invoice_sequences_pkey: first-of-year sequence race, retry once.
    - uq_payments_tenant_refnum: bank reference already used, clean 409.
    - anything else: re-raise.
    """
    constraint = get_constraint_name(exc)

    if constraint == "invoice_sequences_pkey":
        if retry_count >= _MAX_SEQUENCE_RETRIES:
            raise exc
        return await _record_payment_idempotent(
            db, tenant_id=tenant_id, user_id=user_id, invoice_id=invoice_id,
            request=request, idempotency_key=idempotency_key, retry_count=retry_count + 1,
        )

    if constraint == "uq_payments_tenant_refnum":
        async with db.begin():
            existing = await payment_repository.get_active_by_reference_number(
                db, tenant_id=tenant_id, reference_number=request.reference_number,
            )
        raise PaymentReferenceAlreadyUsedError(
            reference_number=request.reference_number,
            existing_payment_number=existing.payment_number if existing else "unknown",
        ) from exc

    raise exc


def _format_elapsed(minutes_ago: int) -> str:
    """Human-friendly elapsed time for the duplicate-payment warning message."""
    if minutes_ago < 60:
        return f"{minutes_ago} minute(s)"
    hours_ago = minutes_ago // 60
    return f"{hours_ago} hour(s)"


async def _record_payment_body(
    db: AsyncSession, *, tenant_id: UUID, user_id: UUID, invoice_id: UUID, request: PaymentCreateRequest,
) -> PaymentRecordedResponse:
    """
    Pure payment logic: owns no transaction, enqueues no tasks.
    Locks the invoice row, validates, allocates, writes payment + invoice state.
    """
    invoice = await invoice_repository.get_by_id_for_update(db, invoice_id=invoice_id, tenant_id=tenant_id)
    if invoice is None:
        raise InvoiceNotFoundError(str(invoice_id))

    try:
        ledger_rules.validate_invoice_accepts_payment(invoice.invoice_status, invoice.invoice_number)
    except ValueError as exc:
        raise InvoiceNotPayableError(
            invoice_number=invoice.invoice_number, current_status=invoice.invoice_status,
        ) from exc

    if invoice.outstanding_amount <= Decimal("0.00"):
        raise InvoiceAlreadyPaidError(invoice.invoice_number)

    try:
        ledger_rules.validate_payment_does_not_exceed_outstanding(
            payment_amount=request.amount, current_outstanding=invoice.outstanding_amount,
        )
    except ValueError as exc:
        raise PaymentExceedsOutstandingError(
            payment_amount=request.amount, outstanding_amount=invoice.outstanding_amount,
            invoice_number=invoice.invoice_number,
        ) from exc

    if request.payment_mode not in REFERENCE_REQUIRED_MODES and not request.confirm_duplicate:
        similar = await payment_repository.find_recent_similar_active_payment(
            db, tenant_id=tenant_id, invoice_id=invoice_id,
            amount=request.amount, payment_mode=request.payment_mode,
            window_minutes=CASH_CARD_DUPLICATE_WINDOW_MINUTES,
        )
        if similar is not None:
            minutes_ago = int((datetime.now(timezone.utc) - similar.created_at).total_seconds() // 60)
            raise PossibleDuplicatePaymentError(
                invoice_number=invoice.invoice_number, amount=request.amount,
                existing_payment_number=similar.payment_number,
                elapsed_display=_format_elapsed(minutes_ago),
            )

    position = ledger_rules.apply_payment(
        invoice_total=invoice.total_amount, paid_amount=invoice.paid_amount,
        credited_amount=invoice.credited_amount, refunded_amount=invoice.refunded_amount,
        new_payment=request.amount,
    )
    payment_number = await sequence_service.get_next_invoice_number(
        db, tenant_id=tenant_id, financial_year=invoice.financial_year, invoice_type="payment",
    )
    payment = await payment_repository.create(
        db, tenant_id=tenant_id, invoice_id=invoice_id, payment_number=payment_number,
        payment_date=request.payment_date, amount=request.amount, payment_mode=request.payment_mode,
        reference_number=request.reference_number, bank_name=request.bank_name,
        notes=request.notes, created_by=user_id,
    )
    await invoice_repository.update_ledger_state(
        db, invoice_id=invoice_id, tenant_id=tenant_id, paid_amount=position.paid_amount,
        credited_amount=position.credited_amount, refunded_amount=position.refunded_amount,
        status=position.status, updated_by=user_id,
    )
    return PaymentRecordedResponse(
        payment=PaymentResponse.model_validate(payment), invoice_id=invoice_id,
        invoice_status=position.status, paid_amount=position.paid_amount,
        outstanding_amount=position.outstanding_amount,
    )


async def cancel_payment(
    db: AsyncSession, *, tenant_id: UUID, cancelled_by: UUID,
    payment_id: UUID, cancellation_reason: str,
) -> None:
    """
    Owns the transaction for the entire cancellation. No idempotency layer,
    deliberately: a double-click or genuine retry lands on the SAME
    payment_id and converges naturally. The first call cancels it; the
    second hits the fast-path status check or the soft_cancel_by_id
    rowcount guard and raises PaymentAlreadyCancelledError.
    """
    cancelled_at = datetime.now(timezone.utc)

    async with db.begin():
        payment = await payment_repository.get_by_id(
            db, payment_id=payment_id, tenant_id=tenant_id,
        )
        if payment is None:
            raise PaymentNotFoundError(str(payment_id))

        # Fast-path check: not the authoritative guard (that is the rowcount
        # below), but avoids taking the invoice lock for the common case of
        # an already-cancelled payment.
        if payment.status == "cancelled":
            raise PaymentAlreadyCancelledError(
                payment_id=str(payment_id),
                payment_number=payment.payment_number,
                cancelled_at=payment.cancelled_at,
            )

        invoice = await invoice_repository.get_by_id_for_update(
            db, invoice_id=payment.invoice_id, tenant_id=tenant_id,
        )
        if invoice is None:
            raise InvoiceNotFoundError(str(payment.invoice_id))

        # AUTHORITATIVE CHECK: runs under the invoice lock. rowcount == 0
        # means a concurrent request already cancelled this payment between
        # the fast-path check and winning the invoice lock.
        rows_affected = await payment_repository.soft_cancel_by_id(
            db, payment_id=payment_id, tenant_id=tenant_id,
            cancelled_by=cancelled_by, cancellation_reason=cancellation_reason,
            cancelled_at=cancelled_at,
        )
        if rows_affected == 0:
            raise PaymentAlreadyCancelledError(
                payment_id=str(payment_id),
                payment_number=payment.payment_number,
                cancelled_at=cancelled_at,
            )

        # Recompute every ledger input from source rows under the invoice lock.
        active_payments_total = await payment_repository.get_total_paid_for_invoice(
            db, invoice_id=invoice.id, tenant_id=tenant_id,
        )
        credited_total = await invoice_repository.get_total_credited(
            db, original_invoice_id=invoice.id, tenant_id=tenant_id,
        )
        refunded_total = await refund_repository.get_total_active_for_invoice(
            db, invoice_id=invoice.id, tenant_id=tenant_id,
        )
        try:
            position = ledger_rules.compute_ledger_position(
                invoice_total=invoice.total_amount, paid_amount=active_payments_total,
                credited_amount=credited_total, refunded_amount=refunded_total,
            )
        except ValueError as exc:
            # Raising rolls back the soft-cancel above, so nothing is half-done.
            raise PaymentCancelBlockedByRefundError(invoice.invoice_number) from exc

        await invoice_repository.update_ledger_state(
            db, invoice_id=invoice.id, tenant_id=tenant_id, paid_amount=position.paid_amount,
            credited_amount=position.credited_amount, refunded_amount=position.refunded_amount,
            status=position.status, updated_by=cancelled_by,
        )

    _enqueue_payment_cancelled_tasks(payment_id=str(payment_id), tenant_id=str(tenant_id))


def _enqueue_payment_cancelled_tasks(*, payment_id: str, tenant_id: str) -> None:
    """Same post-commit-only rule as _enqueue_payment_recorded_tasks. Stub."""
    pass


async def list_payments(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    invoice_id: UUID | None,
    status: str | None,
    date_from: date | None,
    date_to: date | None,
    cursor: str | None,
    limit: int,
) -> Page[PaymentResponse]:
    """Cursor-paginated payment list, newest first."""
    if date_from is not None and date_to is not None and date_from > date_to:
        raise InvalidListQueryError("date_from cannot be after date_to.")
    after = decode_date_cursor(cursor)

    async with db.begin():
        rows = await payment_repository.list_page(
            db, tenant_id=tenant_id, invoice_id=invoice_id, status=status,
            date_from=date_from, date_to=date_to, after=after, limit=limit + 1,
        )

    page_rows = rows[:limit]
    items = [PaymentResponse.model_validate(payment) for payment in page_rows]
    next_cursor = None
    if len(rows) > limit:
        last = page_rows[-1]
        next_cursor = encode_cursor(last.payment_date.isoformat(), last.id)
    return Page[PaymentResponse](items=items, next_cursor=next_cursor)