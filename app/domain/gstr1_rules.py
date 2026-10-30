from __future__ import annotations
 
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
 
from app.models.enum import InvoiceStatus, InvoiceType, SupplyType
 
ZERO = Decimal("0.00")
 
# ── REPORTING SCOPE ──────────────────────────────────────────────────────────
 
# Documents that count as "issued" and therefore enter a return.
# draft     -> never issued, no tax event
# cancelled -> stopped before it became a legal record
# void      -> invalidated after issue; shown only in the document summary
REPORTABLE_STATUSES: tuple[str, ...] = (
    InvoiceStatus.SENT.value,
    InvoiceStatus.PARTIAL.value,
    InvoiceStatus.PAID.value,
    InvoiceStatus.OVERDUE.value,
)
CANCELLED_STATUSES: tuple[str, ...] = (
    InvoiceStatus.CANCELLED.value,
    InvoiceStatus.VOID.value,
)
 
# Outward documents are sales invoices plus credit/debit notes raised against
# a sales invoice. Notes raised against a PURCHASE invoice belong to the
# purchase side (ITC reversal) and are excluded here.
OUTWARD_NOTE_TYPES: tuple[str, ...] = (
    InvoiceType.CREDIT_NOTE.value,
    InvoiceType.DEBIT_NOTE.value,
)
OUTWARD_DOCUMENT_TYPES: tuple[str, ...] = (InvoiceType.SALES.value,) + OUTWARD_NOTE_TYPES
 
# Inter-state supply to an unregistered buyer above this invoice value is
# reported invoice-by-invoice (B2C Large), otherwise consolidated (B2C Small).
# CONFIRM WITH YOUR CA before relying on it: the limit was reduced from
# Rs 2.5 lakh to Rs 1 lakh with effect from the Aug-2024 return period.
B2CL_THRESHOLD: Decimal = Decimal("100000.00")
 
GST_LAUNCH = date(2017, 7, 1)
 
_RETURN_PERIOD_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_TRAILING_NUMBER_RE = re.compile(r"^(.*?)(\d+)$")
 
 
# ── RETURN PERIOD ────────────────────────────────────────────────────────────
 
@dataclass(frozen=True)
class ReturnPeriod:
    label: str            # "2026-09"
    start: date           # 2026-09-01
    end: date             # 2026-09-30
    financial_year: str   # "2026-27"
 
 
def financial_year_for(day: date) -> str:
    """Indian FY runs 1 Apr - 31 Mar. 2026-09-15 -> '2026-27'; 2027-02-10 -> '2026-27'."""
    start_year = day.year if day.month >= 4 else day.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"
 
 
def parse_return_period(label: str) -> ReturnPeriod:
    """
    '2026-09' -> ReturnPeriod. Raises ValueError on any malformed or
    pre-GST period; the service maps that to an HTTP 422.
    """
    match = _RETURN_PERIOD_RE.match(label or "")
    if match is None:
        raise ValueError(f"'{label}' is not in YYYY-MM format")
 
    year, month = int(match.group(1)), int(match.group(2))
    start = date(year, month, 1)
    if start < date(GST_LAUNCH.year, GST_LAUNCH.month, 1):
        raise ValueError("return periods before 2017-07 do not exist")
 
    next_month_start = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    end = date.fromordinal(next_month_start.toordinal() - 1)
    return ReturnPeriod(
        label=f"{year:04d}-{month:02d}",
        start=start,
        end=end,
        financial_year=financial_year_for(start),
    )
 
 
# ── SIGN CONVENTION ──────────────────────────────────────────────────────────
 
def sign_for(invoice_type: str) -> Decimal:
    """
    Credit notes are STORED as positive amounts (a credit note for Rs 590 has
    total_amount = 590). When a section is netted (B2C Small, HSN, Table 8,
    grand totals) a credit note must REDUCE the figure, so it is signed -1.
    Debit notes and sales invoices are +1.
    """
    return Decimal("-1") if invoice_type == InvoiceType.CREDIT_NOTE.value else Decimal("1")
 
 
# ── CLASSIFICATION ───────────────────────────────────────────────────────────
 
class OutwardSection(str, Enum):
    B2B = "b2b"                      # Table 4A
    B2B_RCM = "b2b_rcm"              # Table 4B
    B2CL = "b2cl"                    # Table 5
    B2CS = "b2cs"                    # Table 7 (consolidated, netted for notes)
    EXPORT = "exp"                   # Table 6A
    SEZ = "sez"                      # Table 6B
    CDNR = "cdnr"                    # Table 9B, registered receiver
    CDNUR = "cdnur"                  # Table 9B, unregistered / export receiver
    NIL_EXEMPT = "nil"               # Table 8
 
 
@dataclass(frozen=True)
class OutwardLine:
    """One (document x GST rate) row, as read from the database."""
    invoice_type: str
    supply_type: str
    party_gstin: str | None
    reverse_charge: bool
    invoice_value: Decimal
    original_invoice_value: Decimal | None
    gst_rate: Decimal
 
 
def classify_outward_line(line: OutwardLine, threshold: Decimal = B2CL_THRESHOLD) -> OutwardSection:
    """
    Decide which GSTR-1 table a document-rate row is reported in.
    Order matters; the first matching rule wins.
    """
    is_note = line.invoice_type in OUTWARD_NOTE_TYPES
    is_registered = line.party_gstin is not None
    is_overseas = line.supply_type in (SupplyType.EXPORT.value, SupplyType.SEZ.value)
 
    # 1. Exports and SEZ supplies keep their own tables at every rate (incl. 0%).
    if is_overseas:
        if is_note:
            return OutwardSection.CDNUR
        return OutwardSection.EXPORT if line.supply_type == SupplyType.EXPORT.value else OutwardSection.SEZ
 
    # 2. Nil-rated / exempt lines are reported ONLY in Table 8, never in 4/5/7/9.
    if line.gst_rate == 0:
        return OutwardSection.NIL_EXEMPT
 
    # 3. Credit / debit notes.
    if is_note:
        if is_registered:
            return OutwardSection.CDNR
        original_value = line.original_invoice_value if line.original_invoice_value is not None else line.invoice_value
        if line.supply_type == SupplyType.INTERSTATE.value and original_value > threshold:
            return OutwardSection.CDNUR
        return OutwardSection.B2CS  # netted into Table 7 with a negative sign
 
    # 4. Sales invoices.
    if is_registered:
        return OutwardSection.B2B_RCM if line.reverse_charge else OutwardSection.B2B
    if line.supply_type == SupplyType.INTERSTATE.value and line.invoice_value > threshold:
        return OutwardSection.B2CL
    return OutwardSection.B2CS
 
 
# ── DOCUMENT SERIES (Table 13) ───────────────────────────────────────────────
 
DOCUMENT_TYPE_LABELS: dict[str, str] = {
    InvoiceType.SALES.value: "Invoices for outward supply",
    InvoiceType.CREDIT_NOTE.value: "Credit Note",
    InvoiceType.DEBIT_NOTE.value: "Debit Note",
}
 
 
@dataclass(frozen=True)
class DocumentSeries:
    document_type: str
    series: str
    first_number: str
    last_number: str
    total_numbers: int      # every non-draft number consumed in the series
    cancelled: int          # cancelled + void
    net_issued: int         # total_numbers - cancelled
 
 
def split_document_number(number: str) -> tuple[str, int]:
    """'INV/2026-27/0042' -> ('INV/2026-27/', 42). No trailing digits -> (number, 0)."""
    match = _TRAILING_NUMBER_RE.match(number)
    if match is None:
        return number, 0
    return match.group(1), int(match.group(2))
 
 
def build_document_series(rows: list[tuple[str, str, str]]) -> list[DocumentSeries]:
    """
    rows: (invoice_type, invoice_number, invoice_status) for every document in
    the period EXCEPT drafts (drafts hold no legal number yet).
    Groups by (type, series prefix); first/last are by numeric suffix, not
    string order, so 'INV/9999' < 'INV/10000' is handled correctly.
    """
    buckets: dict[tuple[str, str], list[tuple[int, str, str]]] = {}
    for invoice_type, number, status in rows:
        series, sequence = split_document_number(number)
        buckets.setdefault((invoice_type, series), []).append((sequence, number, status))
 
    result: list[DocumentSeries] = []
    for (invoice_type, series), members in sorted(buckets.items()):
        members.sort(key=lambda m: (m[0], m[1]))
        cancelled = sum(1 for _, _, status in members if status in CANCELLED_STATUSES)
        result.append(
            DocumentSeries(
                document_type=DOCUMENT_TYPE_LABELS.get(invoice_type, invoice_type),
                series=series,
                first_number=members[0][1],
                last_number=members[-1][1],
                total_numbers=len(members),
                cancelled=cancelled,
                net_issued=len(members) - cancelled,
            )
        )
    return result
 
