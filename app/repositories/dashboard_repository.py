from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_RECEIVABLES = text("""
    SELECT COALESCE(SUM(outstanding_amount), 0) AS total_outstanding,
           COUNT(*) AS open_invoices,
           COALESCE(SUM(outstanding_amount) FILTER (WHERE due_date < :today), 0) AS overdue_outstanding,
           COUNT(*) FILTER (WHERE due_date < :today) AS overdue_invoices
    FROM invoices
    WHERE tenant_id = :tenant_id
      AND invoice_status IN ('sent', 'partial')
      AND invoice_type IN ('sales', 'debit_note')
""")

_REFUNDS_DUE = text("""
    SELECT COALESCE(SUM(refund_due_amount), 0) AS total_refund_due,
           COUNT(*) AS invoices_with_refund_due
    FROM invoices
    WHERE tenant_id = :tenant_id AND refund_due_amount > 0
""")

_SALES_THIS_MONTH = text("""
    SELECT COALESCE(SUM(CASE WHEN invoice_type = 'credit_note' THEN -taxable_amount ELSE taxable_amount END), 0)
               AS taxable_amount,
           COALESCE(SUM(CASE WHEN invoice_type = 'credit_note'
                             THEN -(cgst_amount + sgst_amount + igst_amount + cess_amount)
                             ELSE (cgst_amount + sgst_amount + igst_amount + cess_amount) END), 0)
               AS gst_amount,
           COALESCE(SUM(CASE WHEN invoice_type = 'credit_note' THEN -total_amount ELSE total_amount END), 0)
               AS total_amount
    FROM invoices
    WHERE tenant_id = :tenant_id
      AND invoice_type IN ('sales', 'debit_note', 'credit_note')
      AND invoice_status IN ('sent', 'partial', 'paid', 'overdue')
      AND invoice_date >= :month_start AND invoice_date <= :month_end
""")

_COLLECTIONS = text("""
    SELECT COALESCE(SUM(amount), 0) AS total_collected, COUNT(*) AS payments_count
    FROM payments
    WHERE tenant_id = :tenant_id AND status = 'active'
      AND payment_date >= :month_start AND payment_date <= :month_end
""")

_STATUS_COUNTS = text("""
    SELECT invoice_status, COUNT(*) AS invoice_count
    FROM invoices
    WHERE tenant_id = :tenant_id AND invoice_type = 'sales'
    GROUP BY invoice_status
""")

_TOP_CUSTOMERS = text("""
    SELECT i.party_id, p.name AS party_name,
           SUM(i.outstanding_amount) AS outstanding, COUNT(*) AS open_invoices
    FROM invoices i
    JOIN parties p ON p.id = i.party_id AND p.tenant_id = i.tenant_id
    WHERE i.tenant_id = :tenant_id
      AND i.invoice_status IN ('sent', 'partial')
      AND i.invoice_type IN ('sales', 'debit_note')
      AND i.outstanding_amount > 0
    GROUP BY i.party_id, p.name
    ORDER BY outstanding DESC
    LIMIT 5
""")


async def fetch_receivables(db: AsyncSession, *, tenant_id: UUID, today: date) -> dict:
    row = (await db.execute(_RECEIVABLES, {"tenant_id": tenant_id, "today": today})).mappings().one()
    return dict(row)


async def fetch_refunds_due(db: AsyncSession, *, tenant_id: UUID) -> dict:
    return dict((await db.execute(_REFUNDS_DUE, {"tenant_id": tenant_id})).mappings().one())


async def fetch_sales_this_month(
    db: AsyncSession, *, tenant_id: UUID, month_start: date, month_end: date,
) -> dict:
    params = {"tenant_id": tenant_id, "month_start": month_start, "month_end": month_end}
    return dict((await db.execute(_SALES_THIS_MONTH, params)).mappings().one())


async def fetch_collections(
    db: AsyncSession, *, tenant_id: UUID, month_start: date, month_end: date,
) -> dict:
    params = {"tenant_id": tenant_id, "month_start": month_start, "month_end": month_end}
    return dict((await db.execute(_COLLECTIONS, params)).mappings().one())


async def fetch_status_counts(db: AsyncSession, *, tenant_id: UUID) -> dict[str, int]:
    rows = (await db.execute(_STATUS_COUNTS, {"tenant_id": tenant_id})).mappings().all()
    return {row["invoice_status"]: row["invoice_count"] for row in rows}


async def fetch_top_customers(db: AsyncSession, *, tenant_id: UUID) -> list[dict]:
    rows = (await db.execute(_TOP_CUSTOMERS, {"tenant_id": tenant_id})).mappings().all()
    return [dict(row) for row in rows]