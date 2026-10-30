from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.database import get_db
from app.schemas.auth import TokenPayload
from app.schemas.gstr1 import Gstr1Report, Gstr1Section
from app.services import gstr1_export, gstr1_service

router = APIRouter(prefix="/gst-reports", tags=["GST Reports"])

# Statutory return data lists every customer and GSTIN, so it is limited to
# the people who prepare and file returns. Widen deliberately, not by default.
_FILER_ROLES = ("owner", "accountant")

# Format is validated in the service so the error uses the standard
# {"error": {"code", "message"}} envelope; the router only bounds the length.
ReturnPeriodQuery = Annotated[
    str,
    Query(min_length=7, max_length=7, description="Return month as YYYY-MM, e.g. 2026-09"),
]


@router.get(
    "/gstr1",
    response_model=Gstr1Report,
    summary="GSTR-1 data for one return period (read-only)",
)
async def get_gstr1(
    return_period: ReturnPeriodQuery,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role(*_FILER_ROLES)),
) -> Gstr1Report:
    """
    B2B, B2B reverse charge, B2C Large, B2C Small, exports, SEZ, credit/debit
    notes, nil/exempt, HSN summary and the document-series summary for one
    month, built only from stored invoice amounts. Permission: owner, accountant.
    """
    return await gstr1_service.get_gstr1_report(
        db, tenant_id=current_user.tenant_id, return_period=return_period
    )


@router.get(
    "/gstr1/export",
    summary="Download one GSTR-1 section as CSV",
    response_class=Response,
)
async def export_gstr1_section(
    return_period: ReturnPeriodQuery,
    section: Annotated[Gstr1Section, Query(description="Which GSTR-1 table to download")],
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role(*_FILER_ROLES)),
) -> Response:
    report = await gstr1_service.get_gstr1_report(
        db,
        tenant_id=current_user.tenant_id,
        return_period=return_period,
        row_limit=gstr1_service.MAX_EXPORT_ROWS,
    )
    body = gstr1_export.render_section_csv(report, section)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="gstr1_{section}_{report.return_period}.csv"',
            "Cache-Control": "no-store",
        },
    )