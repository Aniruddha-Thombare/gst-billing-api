from datetime import date 
from uuid import UUID
from decimal import Decimal 

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.models.tenant_compliance import TenantCompliance 

async def create(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        financial_year: str,
        annual_turnover: Decimal,
        composition_turnover: Decimal,
        is_msme: bool,
        effective_from: date,
        effective_to: date | None,
) -> TenantCompliance:
    """
    Insert a TenantCompliance row. 

    Called inside auth_service.register() async with db.begin() block,
    which means if any part of registration fails (tenant, user, or compliance
    insert), ALL three rows roll back together. The tenant never exists in the
    DB without its initial compliance profile.

    """
    compliance = TenantCompliance(
        tenant_id=tenant_id,
        financial_year=financial_year,
        annual_turnover=annual_turnover,
        composition_turnover=composition_turnover,
        is_msme=is_msme,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    db.add(compliance)
    await db.flush()
    return compliance


async def get_by_tenant_and_fy(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    financial_year: str,
) -> TenantCompliance | None:
    """
    Fetch a compliance profile for an exact (tenant, financial_year) pair.

    Not currently called by auth_service.register() — a brand-new tenant
    can never already have a compliance row for any financial year, so
    there is nothing to duplicate-check on registration. This function
    exists for a future FY-rollover endpoint (create the new year's
    profile, close_profile() the prior one) and for any admin/compliance
    lookup screen.
    """
    result = await db.execute(
        select(TenantCompliance).where(
            TenantCompliance.tenant_id == tenant_id,
            TenantCompliance.financial_year == financial_year,
        )
    )
    return result.scalar_one_or_none()


async def get_active_for_tenant(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        as_of_date: date, 
) -> TenantCompliance | None:
    """
    Fetch the Compliance Data for an active tenant


    CALLED BY: invoice_service.create_invoice() to retrieve annual_turnover
    for HSN digit requirement and e-invoice applicability checks.

    "Active" means:
      effective_from <= as_of_date
      AND (effective_to IS NULL OR effective_to >= as_of_date)

    Returns the most recently started profile matching those criteria
    (ORDER BY effective_from DESC LIMIT 1).

    WHY as_of_date = invoice_date (not today):
    An invoice dated 2024-03-31 (end of FY 2023-24) must use the compliance
    profile that was active on that date — not today's profile, which may
    belong to FY 2024-25 with a different turnover. The invoice must reflect
    the statutory position at the TIME of issue.

    """
    result = await db.execute(
        select(TenantCompliance)
        .where(
            TenantCompliance.tenant_id == tenant_id,
            TenantCompliance.effective_from <= as_of_date,
            (TenantCompliance.effective_to.is_(None)) |
            (TenantCompliance.effective_to >= as_of_date),
        )
        .order_by(TenantCompliance.effective_from.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def close_profile(
        db: AsyncSession,
        *, 
        tenant_id: UUID,
        financial_year: str,
        effective_to: date,
) -> None:
    """
    Closes a compliance profile by setting its effective_to date.
    Called when a new FY profile is created — the old profile is
    closed so get_active_for_tenant() never returns two active rows.
    """
    await db.execute(
        update(TenantCompliance)
        .where(
            TenantCompliance.tenant_id==tenant_id,
            TenantCompliance.financial_year==financial_year,
        )
        .values(effective_to=effective_to)
        .execution_options(synchronize_session=False)

    )