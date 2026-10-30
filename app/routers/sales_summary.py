from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.database import get_db
from app.domain.sales_summary_rules import Granularity
from app.schemas.auth import TokenPayload
from app.schemas.sales_summary import SalesSummaryReport
from app.services import sales_summary_service

router = APIRouter(prefix="/reports", tags=["Reports"])

# Aggregate business figures (no customer names or GSTINs): viewers may read them.
_REPORT_ROLES = ("owner", "accountant", "viewer")


@router.get(
    "/sales-summary",
    response_model=SalesSummaryReport,
    summary="Sales by week / month / quarter / financial year (read-only)",
)
async def get_sales_summary(
    granularity: Annotated[Granularity, Query(description="week, month, quarter or year (financial year)")],
    from_date: Annotated[date, Query(description="First day, YYYY-MM-DD")],
    to_date: Annotated[date, Query(description="Last day, YYYY-MM-DD")],
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role(*_REPORT_ROLES)),
) -> SalesSummaryReport:
    return await sales_summary_service.get_sales_summary(
        db,
        tenant_id=current_user.tenant_id,
        granularity=granularity,
        from_date=from_date,
        to_date=to_date,
    )
