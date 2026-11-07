from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import dashboard_rules
from app.repositories import dashboard_repository
from app.schemas.dashboard import (
    CollectionsWidget, DashboardResponse, MonthSalesWidget, ReceivablesWidget,
    RefundsDueWidget, TopCustomer,
)
from app.services.report_common import today_ist


async def get_dashboard(db: AsyncSession, *, tenant_id: UUID) -> DashboardResponse:
    """
    Read-only. All widgets come from ONE REPEATABLE READ snapshot so they are
    mutually consistent. Stored amounts only, nothing is recomputed.
    Overdue = open receivable with due_date before today (invoices with no
    due date are not counted as overdue).
    """
    today = today_ist()
    month_start, month_end = dashboard_rules.month_bounds(today)

    async with db.begin():
        await db.connection(
            execution_options={"isolation_level": "REPEATABLE READ", "postgresql_readonly": True}
        )
        receivables = await dashboard_repository.fetch_receivables(db, tenant_id=tenant_id, today=today)
        refunds_due = await dashboard_repository.fetch_refunds_due(db, tenant_id=tenant_id)
        sales = await dashboard_repository.fetch_sales_this_month(
            db, tenant_id=tenant_id, month_start=month_start, month_end=month_end,
        )
        collections = await dashboard_repository.fetch_collections(
            db, tenant_id=tenant_id, month_start=month_start, month_end=month_end,
        )
        status_counts = await dashboard_repository.fetch_status_counts(db, tenant_id=tenant_id)
        top_customers = await dashboard_repository.fetch_top_customers(db, tenant_id=tenant_id)

    return DashboardResponse(
        as_of=datetime.now(timezone.utc), today=today,
        month_start=month_start, month_end=month_end,
        receivables=ReceivablesWidget(**receivables),
        refunds_due=RefundsDueWidget(**refunds_due),
        sales_this_month=MonthSalesWidget(**sales),
        collections_this_month=CollectionsWidget(**collections),
        sales_invoice_counts_by_status=status_counts,
        top_customers_by_outstanding=[TopCustomer(**row) for row in top_customers],
    )