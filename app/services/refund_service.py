import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_errors import get_constraint_name
from app.core.exceptions import (
    InvoiceNotFoundError, RefundExceedsDueError, RefundReferenceAlreadyUsedError,
    RefundNotFoundError, RefundAlreadyCancelledError
)
from app.domain import ledger_rules
from app.repositories import invoice_repository, refund_repository, payment_repository
from app.schemas.refund import RefundCreateRequest, RefundRecordedResponse, RefundResponse
from app.services import idempotency_service, sequence_service

_MAX_SEQUENCE_RETRIES = 1


def _fingerprint(*, invoice_id: UUID, request: RefundCreateRequest) -> str:
    """Business-relevant fingerprint of a refund request (excludes notes)."""
    payload = {
        "invoice_id": str(invoice_id), "amount": str(request.amount),
        "refund_mode": request.refund_mode, "reference_number": request.reference_number,
        "refund_date": request.refund_date.isoformat(), "bank_name": request.bank_name,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def record_refund(
    db: AsyncSession, *, tenant_id: UUID, user_id: UUID, invoice_id: UUID,
    request: RefundCreateRequest, idempotency_key: str,
) -> RefundRecordedResponse:
    """Idempotency-Key is mandatory (required header): a repeated refund is real money lost."""
    return await _record_refund_idempotent(
        db, tenant_id=tenant_id, user_id=user_id, invoice_id=invoice_id,
        request=request, idempotency_key=idempotency_key, retry_count=0,
    )


async def _record_refund_idempotent(
    db: AsyncSession, *, tenant_id: UUID, user_id: UUID, invoice_id: UUID,
    request: RefundCreateRequest, idempotency_key: str, retry_count: int,
) -> RefundRecordedResponse:
    """Owns the one transaction: idempotency reservation + refund body + completion."""
    request_hash = _fingerprint(invoice_id=invoice_id, request=request)
    try:
        async with db.begin():
            outcome = await idempotency_service.try_reserve(
                db, tenant_id=tenant_id, endpoint="record_refund",
                idempotency_key=idempotency_key, request_hash=request_hash,
            )
            if outcome.is_replay:
                return RefundRecordedResponse.model_validate_json(outcome.cached_response)

            response = await _record_refund_body(
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
    return response


async def _retry_or_raise(
    db: AsyncSession, exc: IntegrityError, *, tenant_id: UUID, user_id: UUID,
    invoice_id: UUID, request: RefundCreateRequest, idempotency_key: str, retry_count: int,
) -> RefundRecordedResponse:
    """Routes IntegrityError by constraint name: sequence race retries once, reused UTR gives 409."""
    constraint = get_constraint_name(exc)

    if constraint == "invoice_sequences_pkey":
        if retry_count >= _MAX_SEQUENCE_RETRIES:
            raise exc
        return await _record_refund_idempotent(
            db, tenant_id=tenant_id, user_id=user_id, invoice_id=invoice_id,
            request=request, idempotency_key=idempotency_key, retry_count=retry_count + 1,
        )

    if constraint == "uq_refunds_tenant_refnum":
        raise RefundReferenceAlreadyUsedError(request.reference_number or "") from exc

    raise exc


async def _record_refund_body(
    db: AsyncSession, *, tenant_id: UUID, user_id: UUID, invoice_id: UUID,
    request: RefundCreateRequest,
) -> RefundRecordedResponse:
    """Pure refund logic: locks the invoice, validates against refund due, writes refund + ledger."""
    invoice = await invoice_repository.get_by_id_for_update(db, invoice_id=invoice_id, tenant_id=tenant_id)
    if invoice is None:
        raise InvoiceNotFoundError(str(invoice_id))

    try:
        position = ledger_rules.apply_refund(
            invoice_total=invoice.total_amount, paid_amount=invoice.paid_amount,
            credited_amount=invoice.credited_amount, refunded_amount=invoice.refunded_amount,
            refund_amount=request.amount,
        )
    except ValueError as exc:
        raise RefundExceedsDueError(
            amount=request.amount, refund_due=invoice.refund_due_amount,
            invoice_number=invoice.invoice_number,
        ) from exc

    refund_number = await sequence_service.get_next_invoice_number(
        db, tenant_id=tenant_id, financial_year=invoice.financial_year, invoice_type="refund",
    )
    refund = await refund_repository.create(
        db, tenant_id=tenant_id, invoice_id=invoice_id, refund_number=refund_number,
        refund_date=request.refund_date, amount=request.amount, refund_mode=request.refund_mode,
        reference_number=request.reference_number, bank_name=request.bank_name,
        notes=request.notes, created_by=user_id,
    )
    await invoice_repository.update_ledger_state(
        db, invoice_id=invoice_id, tenant_id=tenant_id, paid_amount=position.paid_amount,
        credited_amount=position.credited_amount, refunded_amount=position.refunded_amount,
        status=position.status, updated_by=user_id,
    )
    return RefundRecordedResponse(
        refund=RefundResponse.model_validate(refund), invoice_id=invoice_id,
        invoice_status=position.status, paid_amount=position.paid_amount,
        credited_amount=position.credited_amount, refunded_amount=position.refunded_amount,
        outstanding_amount=position.outstanding_amount, refund_due_amount=position.refund_due_amount,
    )


async def list_refunds(
    db: AsyncSession, *, invoice_id: UUID, tenant_id: UUID,
) -> list[RefundResponse]:
    """All refunds of one invoice (a short list). Other tenants' invoices return an empty list."""
    async with db.begin():
        rows = await refund_repository.list_for_invoice(db, invoice_id=invoice_id, tenant_id=tenant_id)
    return [RefundResponse.model_validate(row) for row in rows]


async def cancel_refund(
    db: AsyncSession, *, tenant_id: UUID, cancelled_by: UUID,
    refund_id: UUID, cancellation_reason: str,
) -> None:
    """
    Soft-cancels a refund and recomputes the invoice ledger.

    No idempotency layer, deliberately: a retry lands on the same refund_id and
    converges on RefundAlreadyCancelledError, so nothing is processed twice.
    Lock order is invoice only (no sequence row is touched), so it cannot
    deadlock with record_refund, record_payment or cancel_payment.
    """
    cancelled_at = datetime.now(timezone.utc)

    async with db.begin():
        refund = await refund_repository.get_by_id(db, refund_id=refund_id, tenant_id=tenant_id)
        if refund is None:
            raise RefundNotFoundError(str(refund_id))

        # Fast path: skips the invoice lock for the common double-click.
        if refund.status == "cancelled":
            raise RefundAlreadyCancelledError(
                str(refund_id), refund.refund_number, refund.cancelled_at,
            )

        invoice = await invoice_repository.get_by_id_for_update(
            db, invoice_id=refund.invoice_id, tenant_id=tenant_id,
        )
        if invoice is None:
            raise InvoiceNotFoundError(str(refund.invoice_id))

        # AUTHORITATIVE CHECK under the invoice lock.
        rows_affected = await refund_repository.soft_cancel_by_id(
            db, refund_id=refund_id, tenant_id=tenant_id, cancelled_by=cancelled_by,
            cancellation_reason=cancellation_reason, cancelled_at=cancelled_at,
        )
        if rows_affected == 0:
            raise RefundAlreadyCancelledError(str(refund_id), refund.refund_number, cancelled_at)

        # Recompute every ledger input from source rows (self-correcting).
        paid_total = await payment_repository.get_total_paid_for_invoice(
            db, invoice_id=invoice.id, tenant_id=tenant_id,
        )
        credited_total = await invoice_repository.get_total_credited(
            db, original_invoice_id=invoice.id, tenant_id=tenant_id,
        )
        refunded_total = await refund_repository.get_total_active_for_invoice(
            db, invoice_id=invoice.id, tenant_id=tenant_id,
        )
        position = ledger_rules.compute_ledger_position(
            invoice_total=invoice.total_amount, paid_amount=paid_total,
            credited_amount=credited_total, refunded_amount=refunded_total,
        )
        await invoice_repository.update_ledger_state(
            db, invoice_id=invoice.id, tenant_id=tenant_id, paid_amount=position.paid_amount,
            credited_amount=position.credited_amount, refunded_amount=position.refunded_amount,
            status=position.status, updated_by=cancelled_by,
        )