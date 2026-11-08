"""
Renders a payment receipt or refund voucher to PDF bytes.

PURE and synchronous, like the invoice renderer: callers run it in a worker
thread. Prints stored values only.
"""

import io
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.domain.document_format import amount_in_words, format_inr
from app.pdf.common import (
    BORDER_COLOR,
    CONTENT_WIDTH,
    HEADER_FILL,
    MARGIN,
    STYLES,
    boxed,
    format_date,
    lines_para,
    make_page_decorator,
    para,
)
from app.pdf.invoice_document import BuyerBlock, SellerBlock
from app.pdf.voucher_document import VoucherPdfData

_AMOUNT_STYLE = ParagraphStyle(
    "voucher_amount", parent=STYLES["right_bold"], fontSize=15, leading=19
)
_AMOUNT_LABEL_STYLE = ParagraphStyle(
    "voucher_amount_label", parent=STYLES["bold"], fontSize=10, leading=19
)


def _seller_flow(seller: SellerBlock) -> list[Flowable]:
    flow: list[Flowable] = [para(seller.legal_name, "seller_name")]
    if seller.trade_name and seller.trade_name != seller.legal_name:
        flow.append(para(f"Trade name: {seller.trade_name}", "muted"))
    flow.append(lines_para(seller.address_lines))
    flow.append(para(f"GSTIN: {seller.gstin}  |  State code: {seller.state_code}", "bold"))
    contact = "  |  ".join(part for part in (seller.phone, seller.email) if part)
    if contact:
        flow.append(para(contact, "muted"))
    return flow


def _buyer_flow(buyer: BuyerBlock, heading: str) -> list[Flowable]:
    flow: list[Flowable] = [
        para(heading, "muted"),
        para(buyer.name, "bold"),
        lines_para(buyer.address_lines),
        para(f"GSTIN: {buyer.gstin or 'Unregistered'}  |  State code: {buyer.state_code}", "bold"),
    ]
    contact = "  |  ".join(part for part in (buyer.phone, buyer.email) if part)
    if contact:
        flow.append(para(contact, "muted"))
    return flow


def _header(data: VoucherPdfData) -> Table:
    right: list[Flowable] = [
        para(data.title, "title"),
        para(f"No: {data.number}", "right_bold"),
        para(f"Date: {format_date(data.voucher_date)}", "right"),
    ]
    return boxed([[_seller_flow(data.seller), right]], [CONTENT_WIDTH * 0.58, CONTENT_WIDTH * 0.42])


def _parties(data: VoucherPdfData) -> Table:
    invoice_flow: list[Flowable] = [
        para("Against invoice", "muted"),
        para(f"Invoice no: {data.invoice_number}", "bold"),
        para(f"Invoice date: {format_date(data.invoice_date)}"),
        para(f"Invoice total: {format_inr(data.invoice_total)}"),
        para(f"Invoice balance as on {format_date(data.generated_on)}: {format_inr(data.invoice_balance)}"),
    ]
    return boxed(
        [[_buyer_flow(data.buyer, data.party_heading), invoice_flow]],
        [CONTENT_WIDTH * 0.58, CONTENT_WIDTH * 0.42],
    )


def _details(data: VoucherPdfData) -> Table:
    rows: list[list[object]] = [[para("Mode", "muted"), para(data.mode, "bold")]]
    if data.reference_number:
        rows.append([para("Reference no.", "muted"), para(data.reference_number, "bold")])
    if data.bank_name:
        rows.append([para("Bank", "muted"), para(data.bank_name, "bold")])
    return boxed(rows, [CONTENT_WIDTH * 0.25, CONTENT_WIDTH * 0.75])


def _amount_box(data: VoucherPdfData) -> KeepTogether:
    amount = Table(
        [[
            _paragraph(data.amount_label, _AMOUNT_LABEL_STYLE),
            _paragraph(format_inr(data.amount), _AMOUNT_STYLE),
        ]],
        colWidths=[CONTENT_WIDTH * 0.6, CONTENT_WIDTH * 0.4],
    )
    amount.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.8, BORDER_COLOR),
                ("BACKGROUND", (0, 0), (-1, -1), HEADER_FILL),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return KeepTogether(
        [amount, Spacer(1, 2 * mm), para("Amount in words", "muted"),
         para(amount_in_words(data.amount), "bold")]
    )


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    """Plain text -> Paragraph in a custom style (escaped, like pdf.common.para)."""
    return Paragraph(escape(text), style)


def _signature(data: VoucherPdfData) -> KeepTogether:
    box = Table(
        [[para(f"For {data.seller.legal_name}", "right_bold")], [Spacer(1, 14 * mm)],
         [para("Authorised signatory", "right")]],
        colWidths=[CONTENT_WIDTH],
    )
    box.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return KeepTogether([box])


def _build_story(data: VoucherPdfData) -> list[Flowable]:
    story: list[Flowable] = [
        _header(data), Spacer(1, 2 * mm),
        _parties(data), Spacer(1, 2 * mm),
        _details(data), Spacer(1, 5 * mm),
        _amount_box(data), Spacer(1, 4 * mm),
    ]
    for remark in data.remarks:
        story.append(para(remark, "bold"))
    if data.cancelled:
        when = f" on {format_date(data.cancelled_on)}" if data.cancelled_on else ""
        story.append(para(f"This document was CANCELLED{when} and is not valid.", "bold"))
    story.extend([Spacer(1, 6 * mm), _signature(data)])
    return story


def render_voucher_pdf(data: VoucherPdfData, *, compress: bool = True) -> bytes:
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN,
        bottomMargin=MARGIN + 6 * mm, title=f"{data.title} {data.number}",
        author=data.seller.legal_name, pageCompression=1 if compress else 0,
    )
    decorate = make_page_decorator(
        footer_left=f"{data.title} {data.number}",
        generated_on=data.generated_on,
        watermark="CANCELLED" if data.cancelled else None,
    )
    document.build(_build_story(data), onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()
