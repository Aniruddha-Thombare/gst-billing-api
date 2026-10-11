# app/services/tenant_compliance_service.py

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateComplianceProfileError
from app.domain.business_rules import get_financial_year
from app.models.tenant_compliance import TenantCompliance
from app.repositories import tenant_compliance_repository
from app.schemas.tenant_compliance import TenantComplianceCreate, TenantComplianceResponse


async def create_or_renew_compliance(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    request: TenantComplianceCreate,
) -> TenantCompliance:
    """
    Creates a new compliance profile for a financial year.

    Called every April when a new FY begins and the tenant's actual
    preceding FY turnover is known. Example:
      April 2025 → create FY "2025-26" profile with actual FY 2024-25 turnover

    Also closes the previous FY profile by setting its effective_to
    to March 31 of the new FY's start year, so the date-based lookup
    always returns exactly one active profile.

    UniqueConstraint on (tenant_id, financial_year) prevents duplicates.
    """
    existing = await tenant_compliance_repository.get_by_tenant_and_fy(
        db,
        tenant_id=tenant_id,
        financial_year=request.financial_year,
    )
    if existing:
        raise DuplicateComplianceProfileError(request.financial_year)

    # Close the previous profile: set effective_to to day before new FY starts
    fy_start_year = int(request.financial_year.split("-")[0])
    new_fy_start = date(fy_start_year, 4, 1)
    previous_fy_end = date(fy_start_year - 1 + 1, 3, 31)  # March 31 of current year

    previous = await tenant_compliance_repository.get_active_for_tenant(
        db,
        tenant_id=tenant_id,
        as_of_date=date(fy_start_year - 1, 12, 31),  # any date in previous FY
    )
    if previous and previous.effective_to is None:
        await tenant_compliance_repository.close_profile(
            db,
            tenant_id=tenant_id,
            financial_year=previous.financial_year,
            effective_to=previous_fy_end,
        )

    async with db.begin():
        compliance = await tenant_compliance_repository.create(
            db,
            tenant_id=tenant_id,
            financial_year=request.financial_year,
            annual_turnover=request.annual_turnover,
            composition_turnover=request.composition_turnover,
            is_msme=request.is_msme,
            effective_from=new_fy_start,
            effective_to=None,
        )

    return compliance