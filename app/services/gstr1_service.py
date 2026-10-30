"""
GSTR-1 service — validates the request, runs the read-only queries in ONE
consistent snapshot, classifies rows with the pure domain rules and
assembles the response. Contains no SQL and performs no writes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ReportTooLargeError
from app.domain.gstr1_rules import (
    B2CL_THRESHOLD,
    ZERO,
    OutwardLine,
    OutwardSection,
    ReturnPeriod,
    build_document_series,
    classify_outward_line,
    sign_for,
)
from app.models.enum import InvoiceType, SupplyType
from app.repositories import gstr1_repository as repo
from app.schemas.gstr1 import (
    B2CSRow,
    DocumentSeriesRow,
    Gstr1Report,
    HsnRow,
    NilExemptRow,
    OutwardDocument,
    RateLine,
    SectionTotals,
    TaxAmounts,
    TenantSummary,
)
from app.services.report_common import (  # noqa: F401  (MAX_* are re-exported for the router)
    MAX_EXPORT_ROWS,
    MAX_JSON_ROWS,
    assert_regular_taxpayer,
    period_warnings,
    resolve_return_period,
    today_ist,
)

logger = logging.getLogger(__name__)

_DOCUMENT_SECTIONS: tuple[OutwardSection, ...] = (
    OutwardSection.B2B,
    OutwardSection.B2B_RCM,
    OutwardSection.B2CL,
    OutwardSection.EXPORT,
    OutwardSection.SEZ,
    OutwardSection.CDNR,
    OutwardSection.CDNUR,
)


# ── SMALL, SINGLE-PURPOSE HELPERS ────────────────────────────────────────────

def _dec(value: Any) -> Decimal:
    return Decimal(value) if value is not None else ZERO


def _line_from_row(row: Any) -> OutwardLine:
    return OutwardLine(
        invoice_type=row["invoice_type"],
        supply_type=row["supply_type"],
        party_gstin=row["party_gstin"],
        reverse_charge=bool(row["reverse_charge"]),
        invoice_value=_dec(row["invoice_value"]),
        original_invoice_value=(
            _dec(row["original_invoice_value"]) if row["original_invoice_value"] is not None else None
        ),
        gst_rate=_dec(row["gst_rate"]),
    )


def _rate_line_from_row(row: Any) -> RateLine:
    return RateLine(
        gst_rate=_dec(row["gst_rate"]),
        taxable_amount=_dec(row["taxable_amount"]),
        igst_amount=_dec(row["igst_amount"]),
        cgst_amount=_dec(row["cgst_amount"]),
        sgst_amount=_dec(row["sgst_amount"]),
        cess_amount=_dec(row["cess_amount"]),
    )


def _note_type(invoice_type: str) -> str | None:
    if invoice_type == InvoiceType.CREDIT_NOTE.value:
        return "C"
    if invoice_type == InvoiceType.DEBIT_NOTE.value:
        return "D"
    return None


def _new_document(row: Any) -> OutwardDocument:
    return OutwardDocument(
        invoice_id=row["invoice_id"],
        document_number=row["invoice_number"],
        document_date=row["invoice_date"],
        document_type=row["invoice_type"],
        note_type=_note_type(row["invoice_type"]),
        party_name=row["party_name"],
        party_gstin=row["party_gstin"],
        place_of_supply=row["place_of_supply"],
        supply_type=row["supply_type"],
        reverse_charge=bool(row["reverse_charge"]),
        document_value=_dec(row["invoice_value"]),
        original_document_number=row["original_invoice_number"],
        original_document_date=row["original_invoice_date"],
    )


def _add_to_document(document: OutwardDocument, line: RateLine) -> None:
    document.items.append(line)
    document.taxable_amount += line.taxable_amount
    document.igst_amount += line.igst_amount
    document.cgst_amount += line.cgst_amount
    document.sgst_amount += line.sgst_amount
    document.cess_amount += line.cess_amount


def _signed_amounts(amounts: TaxAmounts, sign: Decimal) -> TaxAmounts:
    return TaxAmounts(
        taxable_amount=amounts.taxable_amount * sign,
        igst_amount=amounts.igst_amount * sign,
        cgst_amount=amounts.cgst_amount * sign,
        sgst_amount=amounts.sgst_amount * sign,
        cess_amount=amounts.cess_amount * sign,
    )


def _accumulate(target: TaxAmounts, amounts: TaxAmounts) -> None:
    target.taxable_amount += amounts.taxable_amount
    target.igst_amount += amounts.igst_amount
    target.cgst_amount += amounts.cgst_amount
    target.sgst_amount += amounts.sgst_amount
    target.cess_amount += amounts.cess_amount


# ── SECTION BUILDERS ─────────────────────────────────────────────────────────

class _Sections:
    """Mutable accumulator filled while walking the rate rows once."""

    def __init__(self) -> None:
        self.documents: dict[OutwardSection, dict[UUID, OutwardDocument]] = {
            section: {} for section in _DOCUMENT_SECTIONS
        }
        self.b2cs: dict[tuple[str, str, Decimal], tuple[B2CSRow, set[UUID]]] = {}
        self.nil: dict[tuple[str, str], tuple[NilExemptRow, set[UUID]]] = {}
        # signed totals per section, for section_totals / net_totals
        self.totals: dict[OutwardSection, TaxAmounts] = {s: TaxAmounts() for s in OutwardSection}
        self.document_ids: dict[OutwardSection, set[UUID]] = {s: set() for s in OutwardSection}

    def add(self, row: Any, section: OutwardSection) -> None:
        sign = sign_for(row["invoice_type"])
        line = _rate_line_from_row(row)
        invoice_id: UUID = row["invoice_id"]
        signed = _signed_amounts(line, sign)

        self.document_ids[section].add(invoice_id)

        if section in _DOCUMENT_SECTIONS:
            bucket = self.documents[section]
            document = bucket.get(invoice_id)
            if document is None:
                document = _new_document(row)
                bucket[invoice_id] = document
            _add_to_document(document, line)
            _accumulate(self.totals[section], signed)
        elif section is OutwardSection.B2CS:
            self._add_b2cs(row, line, signed, invoice_id)
            _accumulate(self.totals[section], signed)
        else:  # NIL_EXEMPT
            self._add_nil(row, signed, invoice_id)
            self.totals[section].taxable_amount += signed.taxable_amount

    def _add_b2cs(self, row: Any, line: RateLine, signed: TaxAmounts, invoice_id: UUID) -> None:
        key = (row["supply_type"], row["place_of_supply"], line.gst_rate)
        entry = self.b2cs.get(key)
        if entry is None:
            entry = (
                B2CSRow(
                    supply_type=row["supply_type"],
                    place_of_supply=row["place_of_supply"],
                    gst_rate=line.gst_rate,
                    document_count=0,
                ),
                set(),
            )
            self.b2cs[key] = entry
        b2cs_row, seen = entry
        _accumulate(b2cs_row, signed)
        seen.add(invoice_id)
        b2cs_row.document_count = len(seen)

    def _add_nil(self, row: Any, signed: TaxAmounts, invoice_id: UUID) -> None:
        supply = (
            "interstate" if row["supply_type"] == SupplyType.INTERSTATE.value else "intrastate"
        )
        receiver = "registered" if row["party_gstin"] is not None else "unregistered"
        entry = self.nil.get((supply, receiver))
        if entry is None:
            entry = (NilExemptRow(supply_type=supply, receiver=receiver), set())
            self.nil[(supply, receiver)] = entry
        nil_row, seen = entry
        nil_row.taxable_amount += signed.taxable_amount
        seen.add(invoice_id)
        nil_row.document_count = len(seen)


def _build_section_totals(sections: _Sections) -> tuple[list[SectionTotals], TaxAmounts]:
    rows: list[SectionTotals] = []
    net = TaxAmounts()
    for section in OutwardSection:
        total = sections.totals[section]
        rows.append(
            SectionTotals(
                section=section.value,
                document_count=len(sections.document_ids[section]),
                **total.model_dump(),
            )
        )
        _accumulate(net, total)
    return rows, net


def _build_hsn(rows: Sequence[Any]) -> list[HsnRow]:
    return [
        HsnRow(
            hsn_sac_code=row["hsn_sac_code"] or None,
            unit=row["unit"],
            gst_rate=_dec(row["gst_rate"]),
            quantity=_dec(row["quantity"]),
            total_value=_dec(row["total_value"]),
            taxable_amount=_dec(row["taxable_amount"]),
            igst_amount=_dec(row["igst_amount"]),
            cgst_amount=_dec(row["cgst_amount"]),
            sgst_amount=_dec(row["sgst_amount"]),
            cess_amount=_dec(row["cess_amount"]),
        )
        for row in rows
    ]


def _build_warnings(
    *, period: ReturnPeriod, draft_count: int, hsn_rows: list[HsnRow], is_period_open: bool
) -> list[str]:
    warnings = period_warnings(
        period_label=period.label, is_period_open=is_period_open, draft_count=draft_count
    )
    if any(row.hsn_sac_code is None for row in hsn_rows):
        warnings.append("Some line items have no HSN/SAC code; they appear with an empty code in the HSN summary.")
    return warnings


# ── PUBLIC API ───────────────────────────────────────────────────────────────

async def get_gstr1_report(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    return_period: str,
    row_limit: int = MAX_JSON_ROWS,
) -> Gstr1Report:
    """
    Build the GSTR-1 data for one monthly return period.

    All queries run in a single READ ONLY / REPEATABLE READ transaction, so
    every section (and the HSN and document tables) is computed from the
    same snapshot: an invoice sent while the report runs cannot appear in
    one section and be missing from another.
    """
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

        hsn_raw = await repo.fetch_hsn_rows(
            db, tenant_id=tenant_id, start_date=period.start, end_date=period.end
        )
        numbered = await repo.fetch_numbered_documents(
            db, tenant_id=tenant_id, start_date=period.start, end_date=period.end, row_limit=row_limit
        )
        if len(numbered) > row_limit:
            raise ReportTooLargeError(row_limit)
        draft_count = await repo.count_draft_documents(
            db, tenant_id=tenant_id, start_date=period.start, end_date=period.end
        )

    sections = _Sections()
    for row in rate_rows:
        sections.add(row, classify_outward_line(_line_from_row(row), B2CL_THRESHOLD))

    section_totals, net_totals = _build_section_totals(sections)
    hsn = _build_hsn(hsn_raw)
    series = build_document_series(
        [(r["invoice_type"], r["invoice_number"], r["invoice_status"]) for r in numbered]
    )

    return Gstr1Report(
        return_period=period.label,
        financial_year=period.financial_year,
        tenant=TenantSummary(
            gstin=profile["gstin"], legal_name=profile["legal_name"], state_code=profile["state_code"]
        ),
        generated_at=datetime.now(timezone.utc),
        b2cl_threshold=B2CL_THRESHOLD,
        is_period_open=is_period_open,
        b2b=list(sections.documents[OutwardSection.B2B].values()),
        b2b_rcm=list(sections.documents[OutwardSection.B2B_RCM].values()),
        b2cl=list(sections.documents[OutwardSection.B2CL].values()),
        b2cs=sorted(
            (entry[0] for entry in sections.b2cs.values()),
            key=lambda r: (r.supply_type, r.place_of_supply, r.gst_rate),
        ),
        exp=list(sections.documents[OutwardSection.EXPORT].values()),
        sez=list(sections.documents[OutwardSection.SEZ].values()),
        cdnr=list(sections.documents[OutwardSection.CDNR].values()),
        cdnur=list(sections.documents[OutwardSection.CDNUR].values()),
        nil=sorted(
            (entry[0] for entry in sections.nil.values()),
            key=lambda r: (r.supply_type, r.receiver),
        ),
        hsn=hsn,
        docs=[DocumentSeriesRow(**vars(item)) for item in series],
        section_totals=section_totals,
        net_totals=net_totals,
        warnings=_build_warnings(
            period=period, draft_count=draft_count, hsn_rows=hsn, is_period_open=is_period_open
        ),
    )
