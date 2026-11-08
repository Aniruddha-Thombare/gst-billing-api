"""Read-only lookups for payment receipts and refund vouchers. All scoped by tenant_id."""

from uuid import UUID

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.payment import Payment
from app.models.refund import Refund


async def get_payment(db: AsyncSession, *, tenant_id: UUID, payment_id: UUID) -> Payment | None:
    result = await db.execute(
        select(Payment).where(Payment.tenant_id == tenant_id, Payment.id == payment_id)
    )
    return result.scalar_one_or_none()


async def get_refund(db: AsyncSession, *, tenant_id: UUID, refund_id: UUID) -> Refund | None:
    result = await db.execute(
        select(Refund).where(Refund.tenant_id == tenant_id, Refund.id == refund_id)
    )
    return result.scalar_one_or_none()


async def get_invoice_summary(
    db: AsyncSession, *, tenant_id: UUID, invoice_id: UUID
) -> Row | None:
    """Only the columns a voucher prints. No line items are loaded."""
    result = await db.execute(
        select(
            Invoice.invoice_number,
            Invoice.invoice_date,
            Invoice.total_amount,
            Invoice.outstanding_amount,
            Invoice.party_id,
            Invoice.party_gstin,
            Invoice.party_state_code,
        ).where(Invoice.tenant_id == tenant_id, Invoice.id == invoice_id)
    )
    return result.one_or_none()
