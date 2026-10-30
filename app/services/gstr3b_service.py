"""
GSTR-3B (outward supplies only) — Table 3.1 and 3.2.

Built from the SAME rows and the SAME classifier as GSTR-1, then mapped onto
3B rows by domain/gstr3b_rules.py, so the two returns agree by construction.
Read-only: one REPEATABLE READ snapshot, no writes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ReportTooLargeError
from app.domain.gstr1_rules import B2CL_THRESHOLD, OutwardLine, classify_outward_line, sign_for
from app.domain.gstr3b_rules import Gstr3bBucket, belongs_in_table_3_2, gstr3b_bucket
from app.repositories import gstr1_repository as repo
from app.schemas.gstr1 import TaxAmounts, TenantSummary
from app.schemas.gstr3b import Gstr3bReport, Table32Row
from app.services.report_common import (
    MAX_JSON_ROWS,
    accumulate,
    assert_regular_taxpayer,
    period_warnings,
    resolve_return_period,
    signed_amounts,
    to_decimal,
    today_ist,
)

_RCM_WARNING = (
    "Outward supplies on reverse charge are shown separately and are not in total_outward. "
    "Confirm with your CA how they must appear in your 3B."
)
_TABLE_3_2_WARNING = (
    "Table 3.2 lists unregistered buyers only; supplies to composition dealers and UIN holders "
    "are not separated in the data."
)


def _line_from_row(row: Any) -> OutwardLine:
    original_value = row["original_invoice_value"]
    return OutwardLine(
        invoice_type=row["invoice_type"],
        supply_type=row["supply_type"],
        party_gstin=row["party_gstin"],
        reverse_charge=bool(row["reverse_charge"]),
        invoice_value=to_decimal(row["invoice_value"]),
        original_invoice_value=to_decimal(original_value) if original_value is not None else None,
        gst_rate=to_decimal(row["gst_rate"]),
    )


def _amounts_from_row(row: Any) -> TaxAmounts:
    return TaxAmounts(
        taxable_amount=to_decimal(row["taxable_amount"]),
        igst_amount=to_decimal(row["igst_amount"]),
        cgst_amount=to_decimal(row["cgst_amount"]),
        sgst_amount=to_decimal(row["sgst_amount"]),
        cess_amount=to_decimal(row["cess_amount"]),
    )


def _build_rows(rate_rows: Any) -> tuple[dict[Gstr3bBucket, TaxAmounts], dict[str, Table32Row]]:
    buckets = {bucket: TaxAmounts() for bucket in Gstr3bBucket}
    table_3_2: dict[str, Table32Row] = {}
    for row in rate_rows:
        section = classify_outward_line(_line_from_row(row), B2CL_THRESHOLD)
        bucket = gstr3b_bucket(section, row["supply_type"])
        signed = signed_amounts(_amounts_from_row(row), sign_for(row["invoice_type"]))
        accumulate(buckets[bucket], signed)
        if belongs_in_table_3_2(bucket, row["supply_type"], row["party_gstin"]):
            entry = table_3_2.setdefault(
                row["place_of_supply"], Table32Row(place_of_supply=row["place_of_supply"])
            )
            entry.taxable_amount += signed.taxable_amount
            entry.igst_amount += signed.igst_amount
    return buckets, table_3_2


def _total_outward(buckets: dict[Gstr3bBucket, TaxAmounts]) -> TaxAmounts:
    total = TaxAmounts()
    for bucket in (Gstr3bBucket.TAXABLE, Gstr3bBucket.ZERO_RATED, Gstr3bBucket.NIL_EXEMPT):
        accumulate(total, buckets[bucket])
    return total


async def get_gstr3b_report(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    return_period: str,
    row_limit: int = MAX_JSON_ROWS,
) -> Gstr3bReport:
    period = resolve_return_period(return_period)
    is_period_open = today_ist() <= period.end

    async with db.begin():
        await db.connection(
            execution_options={"isolation_level": "REPEATABLE READ", "postgresql_readonly": True}
        )
        profile = await repo.get_tenant_profile(db, tenant_id=tenant_id)
        assert_regular_taxpayer(profile)
        rate_rows = await repo.fetch_outward_rate_rows(
            db, tenant_id=tenant_id, start_date=period.start, end_date=period.end, row_limit=row_limit
        )
        if len(rate_rows) > row_limit:
            raise ReportTooLargeError(row_limit)
        draft_count = await repo.count_draft_documents(
            db, tenant_id=tenant_id, start_date=period.start, end_date=period.end
        )

    buckets, table_3_2 = _build_rows(rate_rows)
    warnings = period_warnings(
        period_label=period.label, is_period_open=is_period_open, draft_count=draft_count
    )
    if any(Decimal(b.taxable_amount) != 0 for b in (buckets[Gstr3bBucket.REVERSE_CHARGE_OUTWARD],)):
        warnings.append(_RCM_WARNING)
    if table_3_2:
        warnings.append(_TABLE_3_2_WARNING)

    return Gstr3bReport(
        return_period=period.label,
        financial_year=period.financial_year,
        tenant=TenantSummary(
            gstin=profile["gstin"], legal_name=profile["legal_name"], state_code=profile["state_code"]
        ),
        generated_at=datetime.now(timezone.utc),
        is_period_open=is_period_open,
        outward_taxable=buckets[Gstr3bBucket.TAXABLE],
        outward_zero_rated=buckets[Gstr3bBucket.ZERO_RATED],
        outward_nil_exempt=buckets[Gstr3bBucket.NIL_EXEMPT],
        outward_reverse_charge=buckets[Gstr3bBucket.REVERSE_CHARGE_OUTWARD],
        total_outward=_total_outward(buckets),
        unregistered_interstate=sorted(table_3_2.values(), key=lambda r: r.place_of_supply),
        warnings=warnings,
    )
