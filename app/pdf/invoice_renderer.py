"""
Renders a GST invoice / debit note / credit note to PDF bytes.

PURE: same input -> same layout. No DB, no clock, no network.
It PRINTS stored values only. It never recomputes tax, totals or balances.
It is synchronous and CPU-bound, so callers run it in a worker thread.
"""

import io
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.domain.document_format import amount_in_words, format_inr, format_plain
from app.domain.pdf_rules import document_title, is_void
from app.models.enum import InvoiceType, SupplyType
from app.pdf.common import (
    BORDER_COLOR,
    CONTENT_WIDTH,
    HEADER_FILL,
    MARGIN,
    boxed,
    format_date,
    lines_para,
    make_page_decorator,
    para,
)
from app.pdf.invoice_document import InvoicePdfData
from app.schemas.invoice import InvoiceResponse, LineItemResponse

_ZERO = Decimal("0")


@dataclass(frozen=True)
class _Column:
    header: str
    weight: float
    align: str  # "left" | "right" | "center"
    value: Callable[[LineItemResponse], str]


def _tax_cell(rate: Decimal, amount: Decimal) -> str:
    return f"{format_plain(rate)}%\n{format_inr(amount)}"


def _line_columns(invoice: InvoiceResponse) -> list[_Column]:
    """Columns depend on the invoice: CGST+SGST vs IGST, optional discount and cess."""
    intrastate = invoice.supply_type == SupplyType.INTRASTATE.value
    has_discount = any(line.discount_amount > _ZERO for line in invoice.line_items)
    has_cess = any(line.cess_amount > _ZERO for line in invoice.line_items)

    columns = [
        _Column("#", 4, "center", lambda line: str(line.line_number)),
        _Column("Description", 20, "left", lambda line: line.description),
        _Column("HSN/SAC", 7, "left", lambda line: line.hsn_sac_code or "-"),
        _Column(
            "Qty", 6, "right",
            lambda line: f"{format_plain(line.quantity)} {line.unit or ''}".strip(),
        ),
        _Column("Rate", 8, "right", lambda line: format_plain(line.rate, min_places=2)),
    ]
    if has_discount:
        columns.append(_Column("Disc.", 7, "right", lambda line: format_inr(line.discount_amount)))
    columns.append(_Column("Taxable", 9, "right", lambda line: format_inr(line.taxable_amount)))
    if intrastate:
        columns.append(
            _Column("CGST", 8, "right", lambda line: _tax_cell(line.cgst_rate, line.cgst_amount))
        )
        columns.append(
            _Column("SGST", 8, "right", lambda line: _tax_cell(line.sgst_rate, line.sgst_amount))
        )
    else:
        columns.append(
            _Column("IGST", 9, "right", lambda line: _tax_cell(line.igst_rate, line.igst_amount))
        )
    if has_cess:
        columns.append(
            _Column("Cess", 7, "right", lambda line: _tax_cell(line.cess_rate, line.cess_amount))
        )
    columns.append(_Column("Total", 10, "right", lambda line: format_inr(line.total_amount)))
    return columns


def _header_block(data: InvoicePdfData) -> Table:
    invoice, seller = data.invoice, data.seller
    seller_flow: list[Flowable] = [para(seller.legal_name, "seller_name")]
    if seller.trade_name and seller.trade_name != seller.legal_name:
        seller_flow.append(para(f"Trade name: {seller.trade_name}", "muted"))
    seller_flow.append(lines_para(seller.address_lines))
    seller_flow.append(para(f"GSTIN: {seller.gstin}  |  State code: {seller.state_code}", "bold"))
    contact = "  |  ".join(part for part in (seller.phone, seller.email) if part)
    if contact:
        seller_flow.append(para(contact, "muted"))

    right_flow: list[Flowable] = [
        para(document_title(invoice.invoice_type), "title"),
        para(f"No: {invoice.invoice_number}", "right_bold"),
        para(f"Date: {format_date(invoice.invoice_date)}", "right"),
    ]
    if invoice.due_date and invoice.invoice_type != InvoiceType.CREDIT_NOTE.value:
        right_flow.append(para(f"Due date: {format_date(invoice.due_date)}", "right"))
    right_flow.append(para(f"Financial year: {invoice.financial_year}", "right"))

    return boxed([[seller_flow, right_flow]], [CONTENT_WIDTH * 0.58, CONTENT_WIDTH * 0.42])


def _party_block(data: InvoicePdfData) -> Table:
    invoice, buyer = data.invoice, data.buyer
    heading = "Billed to" if invoice.invoice_type != InvoiceType.CREDIT_NOTE.value else "Credited to"

    buyer_flow: list[Flowable] = [
        para(heading, "muted"),
        para(buyer.name, "bold"),
        lines_para(buyer.address_lines),
        para(f"GSTIN: {buyer.gstin or 'Unregistered'}  |  State code: {buyer.state_code}", "bold"),
    ]
    contact = "  |  ".join(part for part in (buyer.phone, buyer.email) if part)
    if contact:
        buyer_flow.append(para(contact, "muted"))

    supply_label = invoice.supply_type.replace("_", "-").title()
    supply_flow: list[Flowable] = [
        para("Supply details", "muted"),
        para(f"Place of supply: {invoice.place_of_supply}"),
        para(f"Supply type: {supply_label}"),
        para(f"Reverse charge: {'Yes' if invoice.reverse_charge else 'No'}"),
    ]
    if data.original:
        supply_flow.append(
            para(
                f"Against invoice: {data.original.invoice_number} "
                f"dated {format_date(data.original.invoice_date)}",
                "bold",
            )
        )
    return boxed([[buyer_flow, supply_flow]], [CONTENT_WIDTH * 0.58, CONTENT_WIDTH * 0.42])


def _line_table(invoice: InvoiceResponse) -> Table:
    columns = _line_columns(invoice)
    total_weight = sum(column.weight for column in columns)
    widths = [CONTENT_WIDTH * column.weight / total_weight for column in columns]

    rows: list[list[object]] = [
        [para(column.header, f"head_{column.align}") for column in columns]
    ]
    for line in invoice.line_items:
        rows.append([para(column.value(line), f"cell_{column.align}") for column in columns])

    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HEADER_FILL),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _summary_rows(invoice: InvoiceResponse) -> list[tuple[str, str, bool]]:
    """(label, amount, bold) rows printed from the invoice's STORED totals."""
    rows: list[tuple[str, str, bool]] = [("Subtotal", format_inr(invoice.subtotal), False)]
    if invoice.discount_amount > _ZERO:
        rows.append(("Discount", f"-{format_inr(invoice.discount_amount)}", False))
    rows.append(("Taxable amount", format_inr(invoice.taxable_amount), False))
    if invoice.supply_type == SupplyType.INTRASTATE.value:
        rows.append(("CGST", format_inr(invoice.cgst_amount), False))
        rows.append(("SGST", format_inr(invoice.sgst_amount), False))
    else:
        rows.append(("IGST", format_inr(invoice.igst_amount), False))
    if invoice.cess_amount > _ZERO:
        rows.append(("Cess", format_inr(invoice.cess_amount), False))
    rows.append(("Total (INR)", format_inr(invoice.total_amount), True))
    return rows


def _settlement_rows(invoice: InvoiceResponse) -> list[tuple[str, str, bool]]:
    """
    Paid / credited / refunded / balance, from stored columns.
    Not for credit notes (nothing to collect) and not for void invoices: a void
    invoice never received payment, but its stored outstanding still equals the
    total, so printing "Balance due" on it would be wrong.
    """
    if invoice.invoice_type == InvoiceType.CREDIT_NOTE.value or is_void(invoice.invoice_status):
        return []
    rows: list[tuple[str, str, bool]] = []
    if invoice.paid_amount > _ZERO:
        rows.append(("Amount received", format_inr(invoice.paid_amount), False))
    if invoice.credited_amount > _ZERO:
        rows.append(("Credit notes applied", format_inr(invoice.credited_amount), False))
    if invoice.refunded_amount > _ZERO:
        rows.append(("Refunded to customer", format_inr(invoice.refunded_amount), False))
    rows.append(("Balance due (INR)", format_inr(invoice.outstanding_amount), True))
    return rows


def _amount_table(rows: list[tuple[str, str, bool]], width: float) -> Table:
    table_rows = [
        [para(label, "bold" if bold else "body"), para(amount, "right_bold" if bold else "right")]
        for label, amount, bold in rows
    ]
    table = Table(table_rows, colWidths=[width * 0.55, width * 0.45])
    style = [
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER_COLOR),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, BORDER_COLOR),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    for index, (_, _, bold) in enumerate(rows):
        if bold:
            style.append(("BACKGROUND", (0, index), (-1, index), HEADER_FILL))
    table.setStyle(TableStyle(style))
    return table


def _totals_section(data: InvoicePdfData) -> KeepTogether:
    invoice = data.invoice
    amounts_width = CONTENT_WIDTH * 0.42
    stacked: list[Flowable] = [_amount_table(_summary_rows(invoice), amounts_width)]
    settlement = _settlement_rows(invoice)
    if settlement:
        stacked.extend([Spacer(1, 4 * mm), _amount_table(settlement, amounts_width)])

    words = [
        para("Amount in words", "muted"),
        para(amount_in_words(invoice.total_amount), "bold"),
    ]
    layout = Table([[words, stacked]], colWidths=[CONTENT_WIDTH * 0.58, amounts_width])
    layout.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 10),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
            ]
        )
    )
    return KeepTogether([layout])


def _notes_section(invoice: InvoiceResponse) -> list[Flowable]:
    flow: list[Flowable] = []
    if invoice.notes:
        flow.extend([para("Notes", "bold"), para(invoice.notes), Spacer(1, 2 * mm)])
    if invoice.terms:
        flow.extend([para("Terms & conditions", "bold"), para(invoice.terms), Spacer(1, 2 * mm)])
    return flow


def _signature_block(data: InvoicePdfData) -> KeepTogether:
    box = Table(
        [[para(f"For {data.seller.legal_name}", "right_bold")], [Spacer(1, 14 * mm)],
         [para("Authorised signatory", "right")]],
        colWidths=[CONTENT_WIDTH],
    )
    box.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return KeepTogether([box])


def _build_story(data: InvoicePdfData) -> list[Flowable]:
    invoice = data.invoice
    story: list[Flowable] = [
        _header_block(data),
        Spacer(1, 2 * mm),
        _party_block(data),
        Spacer(1, 4 * mm),
        _line_table(invoice),
        Spacer(1, 4 * mm),
        _totals_section(data),
        Spacer(1, 5 * mm),
    ]
    story.extend(_notes_section(invoice))
    story.append(_signature_block(data))
    return story


def render_invoice_pdf(data: InvoicePdfData, *, compress: bool = True) -> bytes:
    """`compress=False` keeps text readable in the raw bytes; used only by tests."""
    invoice = data.invoice
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN + 6 * mm,
        title=f"{document_title(invoice.invoice_type)} {invoice.invoice_number}",
        author=data.seller.legal_name,
        pageCompression=1 if compress else 0,
    )
    decorate = make_page_decorator(
        footer_left=f"{document_title(invoice.invoice_type)} {invoice.invoice_number}",
        generated_on=data.generated_on,
        watermark="VOID" if is_void(invoice.invoice_status) else None,
    )
    document.build(_build_story(data), onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()
