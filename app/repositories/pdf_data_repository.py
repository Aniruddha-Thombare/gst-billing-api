"""Read-only lookups the PDF layer needs. Every query is scoped by tenant_id."""

from uuid import UUID

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.party import Party
from app.models.tenant import Tenant


async def get_tenant(db: AsyncSession, *, tenant_id: UUID) -> Tenant | None:
    """The seller. A tenant's own row is identified by id == tenant_id."""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    return result.scalar_one_or_none()


async def get_party(db: AsyncSession, *, tenant_id: UUID, party_id: UUID) -> Party | None:
    result = await db.execute(
        select(Party).where(Party.tenant_id == tenant_id, Party.id == party_id)
    )
    return result.scalar_one_or_none()


async def get_invoice_reference(
    db: AsyncSession, *, tenant_id: UUID, invoice_id: UUID
) -> Row[tuple[str, object]] | None:
    """Number and date of another invoice (the original of a credit/debit note)."""
    result = await db.execute(
        select(Invoice.invoice_number, Invoice.invoice_date).where(
            Invoice.tenant_id == tenant_id, Invoice.id == invoice_id
        )
    )
    return result.one_or_none()
