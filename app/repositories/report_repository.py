from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, case, func, literal_column, or_, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.aging_rules import BucketBoundaries
from app.models.invoice import Invoice
from app.models.party import Party

# Literal SQL constants (not bound parameters), so Postgres can match the
# partial index idx_invoices_open_receivables on every execution.
_OPEN_STATUSES = (literal_column("'sent'"), literal_column("'partial'"))
_RECEIVABLE_TYPES = (literal_column("'sales'"), literal_column("'debit_note'"))
_SQL_ZERO = literal_column("0")

# Effective due date: due_date, or invoice_date when no due date was given.
_EFFECTIVE_DUE = func.coalesce(Invoice.due_date, Invoice.invoice_date)


def _open_receivable_conditions(
    *,
    tenant_id: UUID,
    party_id: UUID | None,
    due_date_from: date | None,
    due_date_to: date | None,
    invoice_date_from: date | None,
    invoice_date_to: date | None,
) -> list:
    """
    WHERE conditions for "money a customer still owes us". Status filtering is
    essential: a draft invoice also has outstanding_amount = total_amount
    (generated column), so drafts must never be counted.
    """
    conditions = [
        Invoice.tenant_id == tenant_id,
        Invoice.invoice_type.in_(_RECEIVABLE_TYPES),
        Invoice.invoice_status.in_(_OPEN_STATUSES),
        Invoice.outstanding_amount > _SQL_ZERO,
    ]
    if party_id is not None:
        conditions.append(Invoice.party_id == party_id)
    if due_date_from is not None:
        conditions.append(_EFFECTIVE_DUE >= due_date_from)
    if due_date_to is not None:
        conditions.append(_EFFECTIVE_DUE <= due_date_to)
    if invoice_date_from is not None:
        conditions.append(Invoice.invoice_date >= invoice_date_from)
    if invoice_date_to is not None:
        conditions.append(Invoice.invoice_date <= invoice_date_to)
    return conditions


def _bucket_sum(label: str, condition):
    """SUM(outstanding) for rows matching the bucket condition; 0 when none."""
    return func.coalesce(
        func.sum(case((condition, Invoice.outstanding_amount), else_=_SQL_ZERO)),
        _SQL_ZERO,
    ).label(label)


def _bucket_columns(b: BucketBoundaries) -> list:
    """The five bucket SUMs, computed in ONE pass over the rows."""
    return [
        _bucket_sum("current_amount", _EFFECTIVE_DUE >= b.as_of),
        _bucket_sum("days_1_30", and_(_EFFECTIVE_DUE >= b.cutoff_30, _EFFECTIVE_DUE < b.as_of)),
        _bucket_sum("days_31_60", and_(_EFFECTIVE_DUE >= b.cutoff_60, _EFFECTIVE_DUE < b.cutoff_30)),
        _bucket_sum("days_61_90", and_(_EFFECTIVE_DUE >= b.cutoff_90, _EFFECTIVE_DUE < b.cutoff_60)),
        _bucket_sum("over_90", _EFFECTIVE_DUE < b.cutoff_90),
    ]


async def aging_summary(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    boundaries: BucketBoundaries,
    party_id: UUID | None,
    due_date_from: date | None,
    due_date_to: date | None,
    invoice_date_from: date | None,
    invoice_date_to: date | None,
) -> Row:
    """
    One row: the five bucket totals, the grand total and the invoice count.
    A single aggregate statement, so every figure comes from the same snapshot.
    """
    stmt = select(
        *_bucket_columns(boundaries),
        func.coalesce(func.sum(Invoice.outstanding_amount), _SQL_ZERO).label("total"),
        func.count(Invoice.id).label("invoice_count"),
    ).where(*_open_receivable_conditions(
        tenant_id=tenant_id, party_id=party_id,
        due_date_from=due_date_from, due_date_to=due_date_to,
        invoice_date_from=invoice_date_from, invoice_date_to=invoice_date_to,
    ))
    result = await db.execute(stmt)
    return result.one()


async def refund_due_summary(
    db: AsyncSession, *, tenant_id: UUID, party_id: UUID | None,
) -> tuple[Decimal, int]:
    """
    Money WE owe customers (refund_due_amount > 0): total and invoice count.
    Reported separately from receivables; never netted. Not affected by the
    date filters.
    """
    conditions = [
        Invoice.tenant_id == tenant_id,
        Invoice.invoice_type.in_(_RECEIVABLE_TYPES),
        Invoice.refund_due_amount > _SQL_ZERO,
    ]
    if party_id is not None:
        conditions.append(Invoice.party_id == party_id)

    result = await db.execute(
        select(
            func.coalesce(func.sum(Invoice.refund_due_amount), _SQL_ZERO),
            func.count(Invoice.id),
        ).where(*conditions)
    )
    total, count = result.one()
    return total, count


async def aging_by_party(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    boundaries: BucketBoundaries,
    party_id: UUID | None,
    due_date_from: date | None,
    due_date_to: date | None,
    invoice_date_from: date | None,
    invoice_date_to: date | None,
    after: tuple[Decimal, UUID] | None,
    limit: int,
) -> list[Row]:
    """
    One row per customer, biggest total first (total DESC, party_id DESC).
    Keyset pagination on the aggregate: `after` is the (total, party_id) of the
    last row of the previous page, applied through HAVING. The caller passes
    limit = page_size + 1 to detect a next page. Party name comes from the
    same query (JOIN, no N+1).
    """
    total_expr = func.coalesce(func.sum(Invoice.outstanding_amount), _SQL_ZERO)

    stmt = (
        select(
            Invoice.party_id.label("party_id"),
            Party.name.label("party_name"),
            *_bucket_columns(boundaries),
            total_expr.label("total"),
            func.count(Invoice.id).label("invoice_count"),
            func.min(_EFFECTIVE_DUE).label("oldest_due_date"),
        )
        .join(Party, and_(Party.id == Invoice.party_id, Party.tenant_id == Invoice.tenant_id))
        .where(*_open_receivable_conditions(
            tenant_id=tenant_id, party_id=party_id,
            due_date_from=due_date_from, due_date_to=due_date_to,
            invoice_date_from=invoice_date_from, invoice_date_to=invoice_date_to,
        ))
        .group_by(Invoice.party_id, Party.name)
    )
    if after is not None:
        after_total, after_party_id = after
        stmt = stmt.having(or_(
            total_expr < after_total,
            and_(total_expr == after_total, Invoice.party_id < after_party_id),
        ))

    stmt = stmt.order_by(total_expr.desc(), Invoice.party_id.desc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.all())