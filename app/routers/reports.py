from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page
from app.database import get_db
from app.models.enum import UserRole
from app.schemas.auth import TokenPayload
from app.schemas.report import ArAgingPartyRow, ArAgingSummaryResponse
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["Reports"])

_READ_ROLES = tuple(role.value for role in UserRole)


@router.get(
    "/ar-aging",
    response_model=ArAgingSummaryResponse,
    summary="AR aging: receivables by how late they are (tenant total)",
)
async def ar_aging_summary(
    as_of_date: date | None = Query(default=None, description="Lateness is measured to this date. Default: today."),
    party_id: UUID | None = None,
    due_date_from: date | None = Query(default=None, description="Only invoices whose due date is on or after this date."),
    due_date_to: date | None = Query(default=None, description="Only invoices whose due date is on or before this date."),
    invoice_date_from: date | None = None,
    invoice_date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role(*_READ_ROLES)),
) -> ArAgingSummaryResponse:
    """
    Permission: any role. Counts sales and debit-note invoices with status
    sent or partial and a balance above zero. Fully paid invoices are never
    listed. Refund due (money owed to customers) is shown separately.
    """
    return await report_service.get_ar_aging_summary(
        db, tenant_id=current_user.tenant_id, as_of_date=as_of_date, party_id=party_id,
        due_date_from=due_date_from, due_date_to=due_date_to,
        invoice_date_from=invoice_date_from, invoice_date_to=invoice_date_to,
    )


@router.get(
    "/ar-aging/parties",
    response_model=Page[ArAgingPartyRow],
    summary="AR aging per customer (biggest debt first)",
)
async def ar_aging_by_party(
    as_of_date: date | None = None,
    party_id: UUID | None = None,
    due_date_from: date | None = None,
    due_date_to: date | None = None,
    invoice_date_from: date | None = None,
    invoice_date_to: date | None = None,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role(*_READ_ROLES)),
) -> Page[ArAgingPartyRow]:
    """Permission: any role. Use this list to decide who to call first."""
    return await report_service.get_ar_aging_by_party(
        db, tenant_id=current_user.tenant_id, as_of_date=as_of_date, party_id=party_id,
        due_date_from=due_date_from, due_date_to=due_date_to,
        invoice_date_from=invoice_date_from, invoice_date_to=invoice_date_to,
        cursor=cursor, limit=limit,
    )