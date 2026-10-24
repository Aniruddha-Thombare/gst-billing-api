from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidListQueryError
from app.core.pagination import Page, decode_cursor, encode_cursor
from app.domain import aging_rules
from app.repositories import report_repository
from app.schemas.report import (
    AgingBuckets, ArAgingFiltersApplied, ArAgingPartyRow, ArAgingSummaryResponse,
)

_TWO_PLACES = Decimal("0.01")


def _money(value) -> Decimal:
    """Normalise DB sums (Decimal or int 0) to two decimal places."""
    return Decimal(value).quantize(_TWO_PLACES)


def _validate_ranges(
    *, due_date_from: date | None, due_date_to: date | None,
    invoice_date_from: date | None, invoice_date_to: date | None,
) -> None:
    if due_date_from and due_date_to and due_date_from > due_date_to:
        raise InvalidListQueryError("due_date_from cannot be after due_date_to.")
    if invoice_date_from and invoice_date_to and invoice_date_from > invoice_date_to:
        raise InvalidListQueryError("invoice_date_from cannot be after invoice_date_to.")


def _decode_party_cursor(cursor: str | None) -> tuple[Decimal, UUID] | None:
    """The cursor holds the last row's (total, party_id). Bad input -> 422."""
    decoded = decode_cursor(cursor)
    if decoded is None:
        return None
    try:
        total = Decimal(decoded[0])
    except InvalidOperation:
        raise InvalidListQueryError("Invalid cursor.")
    if not total.is_finite():
        raise InvalidListQueryError("Invalid cursor.")
    return total, decoded[1]


def _buckets_from_row(row: Row) -> dict:
    return {
        "current": _money(row.current_amount),
        "days_1_30": _money(row.days_1_30),
        "days_31_60": _money(row.days_31_60),
        "days_61_90": _money(row.days_61_90),
        "over_90": _money(row.over_90),
        "total": _money(row.total),
        "invoice_count": row.invoice_count,
    }


async def get_ar_aging_summary(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    as_of_date: date | None,
    party_id: UUID | None,
    due_date_from: date | None,
    due_date_to: date | None,
    invoice_date_from: date | None,
    invoice_date_to: date | None,
) -> ArAgingSummaryResponse:
    """Tenant-wide aging buckets plus the separate refund-due figure."""
    _validate_ranges(
        due_date_from=due_date_from, due_date_to=due_date_to,
        invoice_date_from=invoice_date_from, invoice_date_to=invoice_date_to,
    )
    as_of = as_of_date or date.today()
    boundaries = aging_rules.bucket_boundaries(as_of)

    async with db.begin():
        row = await report_repository.aging_summary(
            db, tenant_id=tenant_id, boundaries=boundaries, party_id=party_id,
            due_date_from=due_date_from, due_date_to=due_date_to,
            invoice_date_from=invoice_date_from, invoice_date_to=invoice_date_to,
        )
        refund_total, refund_count = await report_repository.refund_due_summary(
            db, tenant_id=tenant_id, party_id=party_id,
        )

    return ArAgingSummaryResponse(
        as_of_date=as_of,
        filters=ArAgingFiltersApplied(
            party_id=party_id, due_date_from=due_date_from, due_date_to=due_date_to,
            invoice_date_from=invoice_date_from, invoice_date_to=invoice_date_to,
        ),
        buckets=AgingBuckets(**_buckets_from_row(row)),
        refund_due_total=_money(refund_total),
        refund_due_invoice_count=refund_count,
    )


async def get_ar_aging_by_party(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    as_of_date: date | None,
    party_id: UUID | None,
    due_date_from: date | None,
    due_date_to: date | None,
    invoice_date_from: date | None,
    invoice_date_to: date | None,
    cursor: str | None,
    limit: int,
) -> Page[ArAgingPartyRow]:
    """One aging row per customer, biggest debt first, cursor-paginated."""
    _validate_ranges(
        due_date_from=due_date_from, due_date_to=due_date_to,
        invoice_date_from=invoice_date_from, invoice_date_to=invoice_date_to,
    )
    after = _decode_party_cursor(cursor)
    boundaries = aging_rules.bucket_boundaries(as_of_date or date.today())

    async with db.begin():
        rows = await report_repository.aging_by_party(
            db, tenant_id=tenant_id, boundaries=boundaries, party_id=party_id,
            due_date_from=due_date_from, due_date_to=due_date_to,
            invoice_date_from=invoice_date_from, invoice_date_to=invoice_date_to,
            after=after, limit=limit + 1,
        )

    page_rows = rows[:limit]
    items = [
        ArAgingPartyRow(
            party_id=row.party_id, party_name=row.party_name,
            oldest_due_date=row.oldest_due_date, **_buckets_from_row(row),
        )
        for row in page_rows
    ]
    next_cursor = None
    if len(rows) > limit:
        last = page_rows[-1]
        next_cursor = encode_cursor(str(_money(last.total)), last.party_id)
    return Page[ArAgingPartyRow](items=items, next_cursor=next_cursor)