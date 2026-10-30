from __future__ import annotations

import csv
import io
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable

from app.schemas.gstr1 import Gstr1Report, Gstr1Section, OutwardDocument

_TWO_PLACES = Decimal("0.01")
_THREE_PLACES = Decimal("0.001")
_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _text(value: str | None) -> str:
    if value is None:
        return ""
    if value.startswith(_DANGEROUS_PREFIXES):
        return "'" + value
    return value


def _money(value: Decimal) -> str:
    return format(value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP), "f")


def _quantity(value: Decimal) -> str:
    return format(value.quantize(_THREE_PLACES, rounding=ROUND_HALF_UP), "f")


def _rate(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _yn(flag: bool) -> str:
    return "Y" if flag else "N"


def _export_type(document: OutwardDocument, prefix: str) -> str:
    """WPAY = tax paid on the export, WOPAY = under LUT / bond (no tax)."""
    return f"{prefix}WPAY" if document.igst_amount > 0 else f"{prefix}WOPAY"


# ── ONE FUNCTION PER SECTION: (header, rows) ─────────────────────────────────

def _b2b(documents: list[OutwardDocument]) -> tuple[list[str], list[list[Any]]]:
    header = [
        "GSTIN/UIN of Recipient", "Receiver Name", "Invoice Number", "Invoice date", "Invoice Value",
        "Place Of Supply", "Reverse Charge", "Rate", "Taxable Value", "Integrated Tax",
        "Central Tax", "State/UT Tax", "Cess",
    ]
    rows = [
        [
            _text(d.party_gstin), _text(d.party_name), _text(d.document_number), d.document_date.isoformat(),
            _money(d.document_value), d.place_of_supply, _yn(d.reverse_charge), _rate(i.gst_rate),
            _money(i.taxable_amount), _money(i.igst_amount), _money(i.cgst_amount), _money(i.sgst_amount),
            _money(i.cess_amount),
        ]
        for d in documents
        for i in d.items
    ]
    return header, rows


def _sections_b2b(report: Gstr1Report) -> tuple[list[str], list[list[Any]]]:
    return _b2b(report.b2b)


def _sections_b2b_rcm(report: Gstr1Report) -> tuple[list[str], list[list[Any]]]:
    return _b2b(report.b2b_rcm)


def _sections_b2cl(report: Gstr1Report) -> tuple[list[str], list[list[Any]]]:
    header = [
        "Invoice Number", "Invoice date", "Invoice Value", "Place Of Supply", "Rate",
        "Taxable Value", "Integrated Tax", "Cess",
    ]
    rows = [
        [
            _text(d.document_number), d.document_date.isoformat(), _money(d.document_value),
            d.place_of_supply, _rate(i.gst_rate), _money(i.taxable_amount),
            _money(i.igst_amount), _money(i.cess_amount),
        ]
        for d in report.b2cl
        for i in d.items
    ]
    return header, rows


def _sections_b2cs(report: Gstr1Report) -> tuple[list[str], list[list[Any]]]:
    header = [
        "Type", "Place Of Supply", "Supply Type", "Rate", "Taxable Value", "Integrated Tax",
        "Central Tax", "State/UT Tax", "Cess", "Documents",
    ]
    rows = [
        [
            "OE", r.place_of_supply, r.supply_type, _rate(r.gst_rate), _money(r.taxable_amount),
            _money(r.igst_amount), _money(r.cgst_amount), _money(r.sgst_amount), _money(r.cess_amount),
            r.document_count,
        ]
        for r in report.b2cs
    ]
    return header, rows


def _sections_exp(report: Gstr1Report) -> tuple[list[str], list[list[Any]]]:
    header = [
        "Export Type", "Invoice Number", "Invoice date", "Invoice Value", "Rate", "Taxable Value",
        "Integrated Tax", "Cess",
    ]
    rows = [
        [
            _export_type(d, "EXP"), _text(d.document_number), d.document_date.isoformat(),
            _money(d.document_value), _rate(i.gst_rate), _money(i.taxable_amount),
            _money(i.igst_amount), _money(i.cess_amount),
        ]
        for d in report.exp
        for i in d.items
    ]
    return header, rows


def _sections_sez(report: Gstr1Report) -> tuple[list[str], list[list[Any]]]:
    header = [
        "GSTIN of Recipient", "Receiver Name", "Invoice Number", "Invoice date", "Invoice Value",
        "Supply Type", "Rate", "Taxable Value", "Integrated Tax", "Cess",
    ]
    rows = [
        [
            _text(d.party_gstin), _text(d.party_name), _text(d.document_number), d.document_date.isoformat(),
            _money(d.document_value), _export_type(d, "SEZ"), _rate(i.gst_rate),
            _money(i.taxable_amount), _money(i.igst_amount), _money(i.cess_amount),
        ]
        for d in report.sez
        for i in d.items
    ]
    return header, rows


def _notes(documents: list[OutwardDocument], *, registered: bool) -> tuple[list[str], list[list[Any]]]:
    lead = ["GSTIN/UIN of Recipient", "Receiver Name"] if registered else ["UR Type"]
    header = lead + [
        "Note Number", "Note date", "Note Type", "Place Of Supply", "Note Value", "Rate",
        "Taxable Value", "Integrated Tax", "Central Tax", "State/UT Tax", "Cess",
        "Original Invoice Number", "Original Invoice date",
    ]
    rows: list[list[Any]] = []
    for d in documents:
        if registered:
            lead_cells = [_text(d.party_gstin), _text(d.party_name)]
        elif d.supply_type in ("export", "sez"):
            lead_cells = [_export_type(d, "EXP" if d.supply_type == "export" else "SEZ")]
        else:
            lead_cells = ["B2CL"]
        for i in d.items:
            rows.append(
                lead_cells
                + [
                    _text(d.document_number), d.document_date.isoformat(), d.note_type or "",
                    d.place_of_supply, _money(d.document_value), _rate(i.gst_rate),
                    _money(i.taxable_amount), _money(i.igst_amount), _money(i.cgst_amount),
                    _money(i.sgst_amount), _money(i.cess_amount),
                    _text(d.original_document_number),
                    d.original_document_date.isoformat() if d.original_document_date else "",
                ]
            )
    return header, rows


def _sections_cdnr(report: Gstr1Report) -> tuple[list[str], list[list[Any]]]:
    return _notes(report.cdnr, registered=True)


def _sections_cdnur(report: Gstr1Report) -> tuple[list[str], list[list[Any]]]:
    return _notes(report.cdnur, registered=False)


def _sections_nil(report: Gstr1Report) -> tuple[list[str], list[list[Any]]]:
    header = ["Supply Type", "Receiver", "Nil Rated / Exempt Taxable Value (net)", "Documents"]
    rows = [[r.supply_type, r.receiver, _money(r.taxable_amount), r.document_count] for r in report.nil]
    return header, rows


def _sections_hsn(report: Gstr1Report) -> tuple[list[str], list[list[Any]]]:
    header = [
        "HSN/SAC", "UQC", "Total Quantity", "Total Value", "Rate", "Taxable Value",
        "Integrated Tax", "Central Tax", "State/UT Tax", "Cess",
    ]
    rows = [
        [
            _text(r.hsn_sac_code), _text(r.unit), _quantity(r.quantity), _money(r.total_value),
            _rate(r.gst_rate), _money(r.taxable_amount), _money(r.igst_amount),
            _money(r.cgst_amount), _money(r.sgst_amount), _money(r.cess_amount),
        ]
        for r in report.hsn
    ]
    return header, rows


def _sections_docs(report: Gstr1Report) -> tuple[list[str], list[list[Any]]]:
    header = ["Nature of Document", "Series", "Sr. No. From", "Sr. No. To", "Total Number", "Cancelled", "Net Issued"]
    rows = [
        [_text(r.document_type), _text(r.series), _text(r.first_number), _text(r.last_number),
         r.total_numbers, r.cancelled, r.net_issued]
        for r in report.docs
    ]
    return header, rows


_RENDERERS: dict[str, Callable[[Gstr1Report], tuple[list[str], list[list[Any]]]]] = {
    "b2b": _sections_b2b,
    "b2b_rcm": _sections_b2b_rcm,
    "b2cl": _sections_b2cl,
    "b2cs": _sections_b2cs,
    "exp": _sections_exp,
    "sez": _sections_sez,
    "cdnr": _sections_cdnr,
    "cdnur": _sections_cdnur,
    "nil": _sections_nil,
    "hsn": _sections_hsn,
    "docs": _sections_docs,
}


def render_section_csv(report: Gstr1Report, section: Gstr1Section) -> str:
    header, rows = _RENDERERS[section](report)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()