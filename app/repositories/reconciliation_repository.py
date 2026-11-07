from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class LedgerMismatch:
    kind: str
    tenant_id: UUID
    invoice_id: UUID
    invoice_number: str
    stored_amount: Decimal
    actual_amount: Decimal


# System-wide read-only checks. Every row returned carries its tenant_id.
_PAID_SQL = text("""
    SELECT i.tenant_id, i.id AS invoice_id, i.invoice_number,
           i.paid_amount AS stored_amount, src.total AS actual_amount
    FROM invoices i
    LEFT JOIN LATERAL (
        SELECT COALESCE(SUM(p.amount), 0) AS total
        FROM payments p
        WHERE p.tenant_id = i.tenant_id AND p.invoice_id = i.id AND p.status = 'active'
    ) src ON TRUE
    WHERE i.invoice_type <> 'credit_note' AND i.paid_amount <> src.total
    ORDER BY i.tenant_id, i.id
    LIMIT :row_limit
""")

_CREDITED_SQL = text("""
    SELECT i.tenant_id, i.id AS invoice_id, i.invoice_number,
           i.credited_amount AS stored_amount, src.total AS actual_amount
    FROM invoices i
    LEFT JOIN LATERAL (
        SELECT COALESCE(SUM(c.total_amount), 0) AS total
        FROM invoices c
        WHERE c.tenant_id = i.tenant_id AND c.original_invoice_id = i.id
          AND c.invoice_type = 'credit_note'
          AND c.invoice_status IN ('sent', 'partial', 'paid')
    ) src ON TRUE
    WHERE i.invoice_type <> 'credit_note' AND i.credited_amount <> src.total
    ORDER BY i.tenant_id, i.id
    LIMIT :row_limit
""")

_REFUNDED_SQL = text("""
    SELECT i.tenant_id, i.id AS invoice_id, i.invoice_number,
           i.refunded_amount AS stored_amount, src.total AS actual_amount
    FROM invoices i
    LEFT JOIN LATERAL (
        SELECT COALESCE(SUM(r.amount), 0) AS total
        FROM refunds r
        WHERE r.tenant_id = i.tenant_id AND r.invoice_id = i.id AND r.status = 'active'
    ) src ON TRUE
    WHERE i.invoice_type <> 'credit_note' AND i.refunded_amount <> src.total
    ORDER BY i.tenant_id, i.id
    LIMIT :row_limit
""")


async def _run(db: AsyncSession, statement, kind: str, limit: int) -> list[LedgerMismatch]:
    result = await db.execute(statement, {"row_limit": limit})
    return [LedgerMismatch(kind=kind, **row) for row in result.mappings().all()]


async def find_paid_amount_mismatches(db: AsyncSession, *, limit: int) -> list[LedgerMismatch]:
    return await _run(db, _PAID_SQL, "paid_amount", limit)


async def find_credited_amount_mismatches(db: AsyncSession, *, limit: int) -> list[LedgerMismatch]:
    return await _run(db, _CREDITED_SQL, "credited_amount", limit)


async def find_refunded_amount_mismatches(db: AsyncSession, *, limit: int) -> list[LedgerMismatch]:
    return await _run(db, _REFUNDED_SQL, "refunded_amount", limit)