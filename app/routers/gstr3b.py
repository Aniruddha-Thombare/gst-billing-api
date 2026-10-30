from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.database import get_db
from app.schemas.auth import TokenPayload
from app.schemas.gstr3b import Gstr3bReport
from app.services import gstr3b_service

router = APIRouter(prefix="/gst-reports", tags=["GST Reports"])

_FILER_ROLES = ("owner", "accountant")


@router.get(
    "/gstr3b",
    response_model=Gstr3bReport,
    summary="GSTR-3B Table 3.1 / 3.2 (outward supplies only, read-only)",
)
async def get_gstr3b(
    return_period: Annotated[str, Query(min_length=7, max_length=7, description="YYYY-MM, e.g. 2026-09")],
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role(*_FILER_ROLES)),
) -> Gstr3bReport:
    """Outward side of GSTR-3B for one month. Inward supplies and ITC arrive with the purchase module."""
    return await gstr3b_service.get_gstr3b_report(
        db, tenant_id=current_user.tenant_id, return_period=return_period
    )
