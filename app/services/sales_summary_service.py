"""
Sales summary — business view of outward sales by week / month / quarter /
financial year. Read-only; figures come from stored line-item amounts.
Credit notes reduce the net figures; debit notes add to them.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidReportRangeError
from app.domain.sales_summary_rules import (
    GRANULARITIES,
    MAX_BUCKETS,
    bucket_end,
    bucket_label,
    bucket_start,
    enumerate_buckets,
)
from app.models.enum import InvoiceType
from app.repositories import sales_summary_repository as repo
from app.schemas.sales_summary import SalesBucket, SalesSummaryReport
from app.services.report_common import to_decimal, today_ist

_ZERO = Decimal("0.00")
_CREDIT = InvoiceType.CREDIT_NOTE.value
_DEBIT = InvoiceType.DEBIT_NOTE.value


def validate_range(granularity: str, from_date: date, to_date: date) -> None:
    if granularity not in GRANULARITIES:
        raise InvalidReportRangeError(f"granularity must be one of {', '.join(GRANULARITIES)}.")
    if from_date > to_date:
        raise InvalidReportRangeError("from_date must not be after to_date.")
    if to_date > today_ist():
        raise InvalidReportRangeError("to_date must not be in the future.")
    if len(enumerate_buckets(granularity, from_date, to_date)) > MAX_BUCKETS:
        raise InvalidReportRangeError(
            f"This range holds more than {MAX_BUCKETS} {granularity} buckets; choose a coarser granularity."
        )


def _empty_bucket(granularity: str, start: date) -> SalesBucket:
    return SalesBucket(
        period_label=bucket_label(granularity, start),
        period_start=start,
        period_end=bucket_end(granularity, start),
    )


def _add_daily_row(bucket: SalesBucket, row: Any) -> None:
    count = int(row["document_count"])
    total_value = to_decimal(row["total_value"])
    taxable = to_decimal(row["taxable_amount"])
    tax = to_decimal(row["tax_amount"])
    if row["invoice_type"] == _CREDIT:
        bucket.credit_note_count += count
        bucket.credit_note_value += total_value
        taxable, tax = -taxable, -tax
    else:
        if row["invoice_type"] == _DEBIT:
            bucket.debit_note_count += count
        else:
            bucket.sales_count += count
        bucket.gross_sales_value += total_value
    bucket.net_taxable_amount += taxable
    bucket.net_tax_amount += tax


def _finish(bucket: SalesBucket) -> None:
    bucket.net_sales_value = bucket.gross_sales_value - bucket.credit_note_value


def _build_totals(buckets: list[SalesBucket], from_date: date, to_date: date) -> SalesBucket:
    totals = SalesBucket(period_label="TOTAL", period_start=from_date, period_end=to_date)
    for bucket in buckets:
        totals.sales_count += bucket.sales_count
        totals.credit_note_count += bucket.credit_note_count
        totals.debit_note_count += bucket.debit_note_count
        totals.gross_sales_value += bucket.gross_sales_value
        totals.credit_note_value += bucket.credit_note_value
        totals.net_taxable_amount += bucket.net_taxable_amount
        totals.net_tax_amount += bucket.net_tax_amount
    _finish(totals)
    return totals


async def get_sales_summary(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    granularity: str,
    from_date: date,
    to_date: date,
) -> SalesSummaryReport:
    validate_range(granularity, from_date, to_date)

    async with db.begin():
        await db.connection(
            execution_options={"isolation_level": "REPEATABLE READ", "postgresql_readonly": True}
        )
        daily_rows = await repo.fetch_daily_sales(
            db, tenant_id=tenant_id, start_date=from_date, end_date=to_date
        )

    by_start = {
        start: _empty_bucket(granularity, start)
        for start in enumerate_buckets(granularity, from_date, to_date)
    }
    for row in daily_rows:
        _add_daily_row(by_start[bucket_start(granularity, row["invoice_date"])], row)
    buckets = list(by_start.values())
    for bucket in buckets:
        _finish(bucket)

    return SalesSummaryReport(
        granularity=granularity,
        from_date=from_date,
        to_date=to_date,
        generated_at=datetime.now(timezone.utc),
        buckets=buckets,
        totals=_build_totals(buckets, from_date, to_date),
    )
