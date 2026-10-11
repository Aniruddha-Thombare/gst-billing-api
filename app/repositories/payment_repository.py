from uuid import UUID
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, tuple_

from app.models.payment import Payment


CASH_CARD_DUPLICATE_WINDOW_MINUTES = 24 * 60


async def get_active_by_reference_number(
    db: AsyncSession, *, tenant_id: UUID, reference_number: str,
) -> Payment | None:
    """
    Used only to build a helpful error message after uq_payments_tenant_refnum
    fires. Filtered to status='active' to match what the DB constraint itself
    now enforces — a cancelled payment's reference number is not a real
    conflict, so it must not be reported as one.
    """
    result = await db.execute(
        select(Payment).where(
            Payment.tenant_id == tenant_id,
            Payment.reference_number == reference_number,
            Payment.status == "active",
        )
    )
    return result.scalar_one_or_none()


async def find_recent_similar_active_payment(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    invoice_id: UUID,
    amount: Decimal,
    payment_mode: str,
    window_minutes: int = CASH_CARD_DUPLICATE_WINDOW_MINUTES,
) -> Payment | None:
    """
    Soft-duplicate heuristic for modes with no natural uniqueness key
    (cash, credit_card). Matches same invoice + same amount + same mode,
    recorded within the last `window_minutes`, and still active — a
    cancelled payment is not a duplicate risk, it's a corrected mistake.
    A hit does NOT block the payment — the service surfaces it to the
    caller for human confirmation.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    result = await db.execute(
        select(Payment)
        .where(
            Payment.tenant_id == tenant_id,
            Payment.invoice_id == invoice_id,
            Payment.amount == amount,
            Payment.payment_mode == payment_mode,
            Payment.status == "active",
            Payment.created_at >= cutoff,
        )
        .order_by(Payment.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    invoice_id: UUID,
    payment_number: str,
    payment_date: date,
    amount: Decimal,
    payment_mode: str,
    reference_number: str | None,
    bank_name: str | None,
    notes: str | None,
    created_by: UUID,
) -> Payment:
    """Insert one payment row. status defaults to 'active' via the model. Does NOT commit."""
    payment = Payment(
        tenant_id=tenant_id,
        invoice_id=invoice_id,
        payment_number=payment_number,
        payment_date=payment_date,
        amount=amount,
        payment_mode=payment_mode,
        reference_number=reference_number,
        bank_name=bank_name,
        notes=notes,
        created_by=created_by,
    )
    db.add(payment)
    await db.flush()
    return payment


async def get_by_id(
    db: AsyncSession, *, payment_id: UUID, tenant_id: UUID,
) -> Payment | None:
    """
    Fetch one payment by id, tenant-scoped. Deliberately NOT status-filtered —
    the caller (payment_service.cancel_payment) needs to see a payment
    regardless of its current status, specifically to check whether it is
    already cancelled and raise a clear PaymentAlreadyCancelledError rather
    than a misleading "not found".
    """
    result = await db.execute(
        select(Payment).where(
            Payment.id == payment_id,
            Payment.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def soft_cancel_by_id(
    db: AsyncSession,
    *,
    payment_id: UUID,
    tenant_id: UUID,
    cancelled_by: UUID,
    cancellation_reason: str,
    cancelled_at: datetime,
) -> int:
    """
    Soft-cancels a payment: UPDATE status='cancelled', never a DELETE — the
    row stays permanently for audit (see Payment model docstring).

    WHERE status='active' is a guard, not a formality: it's what makes this
    UPDATE's rowcount the authoritative answer to "did I actually cancel
    this, or did someone else already cancel it between my read and this
    write." Returns the number of rows affected (0 or 1).

    CALLER MUST CHECK THE RETURN VALUE. A 0 means this payment was already
    cancelled by a concurrent request that won a race on the invoice lock —
    the caller must treat that as PaymentAlreadyCancelledError, not as a
    silent success. This is the exact bug found and fixed earlier in this
    project's payment-cancellation design: an earlier version of this
    function returned None and let a double-cancellation pass through
    unnoticed.
    """
    result = await db.execute(
        update(Payment)
        .where(
            Payment.id == payment_id,
            Payment.tenant_id == tenant_id,
            Payment.status == "active",
        )
        .values(
            status="cancelled",
            cancelled_at=cancelled_at,
            cancelled_by=cancelled_by,
            cancellation_reason=cancellation_reason,
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount


async def get_total_paid_for_invoice(
    db: AsyncSession, *, invoice_id: UUID, tenant_id: UUID,
) -> Decimal:
    """
    Defensive SUM recompute: total of all ACTIVE payments against one
    invoice, right now, from source rows — not a cached running total.

    WHY recompute instead of arithmetic (previous_paid_amount - cancelled_amount):
    arithmetic on a running total compounds any past bug or edge case;
    recomputing from source rows is always self-correcting. This is the
    same principle applied when recording a payment (ledger_rules.allocate_payment
    trusts nothing, re-derives from first principles) — cancellation trusts
    nothing either.

    Returns Decimal("0.00") if no active payments remain, never None —
    func.coalesce guards against SUM() returning NULL on zero matching rows.
    """
    result = await db.execute(
        select(func.coalesce(func.sum(Payment.amount), Decimal("0.00")))
        .where(
            Payment.tenant_id == tenant_id,
            Payment.invoice_id == invoice_id,
            Payment.status == "active",
        )
    )
    return result.scalar_one()


async def list_page(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    invoice_id: UUID | None,
    status: str | None,
    date_from: date | None,
    date_to: date | None,
    after: tuple[date, UUID] | None,
    limit: int,
) -> list[Payment]:
    """
    One page of payments, newest first (payment_date DESC, id DESC).
    Keyset pagination; the caller passes limit = page_size + 1.
    Cancelled payments are included unless filtered by status.
    """
    stmt = select(Payment).where(Payment.tenant_id == tenant_id)
    if invoice_id is not None:
        stmt = stmt.where(Payment.invoice_id == invoice_id)
    if status is not None:
        stmt = stmt.where(Payment.status == status)
    if date_from is not None:
        stmt = stmt.where(Payment.payment_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Payment.payment_date <= date_to)
    if after is not None:
        stmt = stmt.where(tuple_(Payment.payment_date, Payment.id) < tuple_(after[0], after[1]))

    stmt = stmt.order_by(Payment.payment_date.desc(), Payment.id.desc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())