from datetime import date, datetime 
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refund import Refund


async def create(
    db: AsyncSession, *, tenant_id: UUID, invoice_id: UUID, refund_number: str,
    refund_date: date, amount: Decimal, refund_mode: str, reference_number: str | None,
    bank_name: str | None, notes: str | None, created_by: UUID,
) -> Refund:
    """Insert one refund row (status defaults to 'active'). Does NOT commit."""
    refund = Refund(
        tenant_id=tenant_id, invoice_id=invoice_id, refund_number=refund_number,
        refund_date=refund_date, amount=amount, refund_mode=refund_mode,
        reference_number=reference_number, bank_name=bank_name, notes=notes,
        created_by=created_by,
    )
    db.add(refund)
    await db.flush()
    return refund


async def get_total_active_for_invoice(
    db: AsyncSession, *, invoice_id: UUID, tenant_id: UUID,
) -> Decimal:
    """Defensive SUM of ACTIVE refunds for one invoice, recomputed from source rows."""
    result = await db.execute(
        select(func.coalesce(func.sum(Refund.amount), Decimal("0.00"))).where(
            Refund.tenant_id == tenant_id, Refund.invoice_id == invoice_id,
            Refund.status == "active",
        )
    )
    return result.scalar_one()


async def list_for_invoice(
    db: AsyncSession, *, invoice_id: UUID, tenant_id: UUID,
) -> list[Refund]:
    """All refunds (active and cancelled) for one invoice, oldest first."""
    result = await db.execute(
        select(Refund)
        .where(Refund.tenant_id == tenant_id, Refund.invoice_id == invoice_id)
        .order_by(Refund.created_at.asc(), Refund.id.asc())
    )
    return list(result.scalars().all())


async def get_active_by_reference_number(
    db: AsyncSession, *, tenant_id: UUID, reference_number: str,
) -> Refund | None:
    """Used only to build a helpful error after uq_refunds_tenant_refnum fires."""
    result = await db.execute(
        select(Refund).where(
            Refund.tenant_id == tenant_id, Refund.reference_number == reference_number,
            Refund.status == "active",
        )
    )
    return result.scalar_one_or_none()


async def get_by_id(
    db: AsyncSession, *, refund_id: UUID, tenant_id: UUID,
) -> Refund | None:
    """
    Fetch one refund by id, tenant-scoped. Deliberately NOT status-filtered,
    so the service can say "already cancelled" instead of "not found".
    """
    result = await db.execute(
        select(Refund).where(Refund.id == refund_id, Refund.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def soft_cancel_by_id(
    db: AsyncSession,
    *,
    refund_id: UUID,
    tenant_id: UUID,
    cancelled_by: UUID,
    cancellation_reason: str,
    cancelled_at: datetime,
) -> int:
    """
    Soft-cancels a refund (never a DELETE). WHERE status='active' makes the
    returned rowcount the authoritative answer to "did I cancel it, or did a
    concurrent request win". CALLER MUST CHECK THE RETURN VALUE: 0 means it
    was already cancelled. Does NOT commit.
    """
    result = await db.execute(
        update(Refund)
        .where(
            Refund.id == refund_id,
            Refund.tenant_id == tenant_id,
            Refund.status == "active",
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