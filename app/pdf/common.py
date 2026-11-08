"""
Shared building blocks for every printed document (invoice, receipt, voucher).

Uses only reportlab's built-in Helvetica, so there is no font file to ship.
That is why amounts are printed as plain numbers under an "(INR)" header
instead of with the rupee glyph, which Helvetica does not contain.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, Table, TableStyle

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 14 * mm
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN

BORDER_COLOR = colors.HexColor("#9CA3AF")
HEADER_FILL = colors.HexColor("#F3F4F6")
MUTED = colors.HexColor("#4B5563")


@dataclass(frozen=True)
class PdfDocument:
    """What a PDF service hands to the router."""

    content: bytes
    filename: str


def _style(name: str, **overrides: object) -> ParagraphStyle:
    base: dict[str, object] = {
        "fontName": "Helvetica",
        "fontSize": 8.5,
        "leading": 11,
        "alignment": TA_LEFT,
    }
    base.update(overrides)
    return ParagraphStyle(name, **base)


STYLES: dict[str, ParagraphStyle] = {
    "body": _style("body"),
    "bold": _style("bold", fontName="Helvetica-Bold"),
    "muted": _style("muted", textColor=MUTED, fontSize=7.5, leading=10),
    "title": _style("title", fontName="Helvetica-Bold", fontSize=15, leading=19, alignment=TA_RIGHT),
    "seller_name": _style("seller_name", fontName="Helvetica-Bold", fontSize=12, leading=15),
    "right": _style("right", alignment=TA_RIGHT),
    "right_bold": _style("right_bold", fontName="Helvetica-Bold", alignment=TA_RIGHT),
    "cell_left": _style("cell_left", fontSize=7.5, leading=9.5),
    "cell_right": _style("cell_right", fontSize=7.5, leading=9.5, alignment=TA_RIGHT),
    "cell_center": _style("cell_center", fontSize=7.5, leading=9.5, alignment=TA_CENTER),
    "head_left": _style("head_left", fontName="Helvetica-Bold", fontSize=7.5, leading=9.5),
    "head_right": _style(
        "head_right", fontName="Helvetica-Bold", fontSize=7.5, leading=9.5, alignment=TA_RIGHT
    ),
    "head_center": _style(
        "head_center", fontName="Helvetica-Bold", fontSize=7.5, leading=9.5, alignment=TA_CENTER
    ),
}


def para(text: object, style: str = "body") -> Paragraph:
    """
    A Paragraph from PLAIN text. Everything is XML-escaped first: reportlab
    parses Paragraph text as markup, so a customer named 'A & B <Traders>'
    would otherwise break the render (or inject markup into the document).
    """
    safe = escape("" if text is None else str(text)).replace("\n", "<br/>")
    return Paragraph(safe, STYLES[style])


def lines_para(lines: Sequence[str], style: str = "body") -> Paragraph:
    return para("\n".join(line for line in lines if line), style)


def format_date(value: date | None) -> str:
    return value.strftime("%d-%m-%Y") if value else "-"


def boxed(rows: list[list[object]], col_widths: Sequence[float]) -> Table:
    """A light-bordered block (used for the header and party panels)."""
    table = Table(rows, colWidths=list(col_widths))
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.6, BORDER_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def make_page_decorator(
    *, footer_left: str, generated_on: date, watermark: str | None = None
) -> Callable[[Canvas, object], None]:
    """Footer on every page (document number, date, page number) plus an optional watermark."""

    def decorate(canvas: Canvas, _doc: object) -> None:
        canvas.saveState()
        if watermark:
            canvas.setFont("Helvetica-Bold", 90)
            canvas.setFillColor(colors.Color(0.85, 0.1, 0.1, alpha=0.12))
            canvas.translate(PAGE_WIDTH / 2, PAGE_HEIGHT / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, watermark)
            canvas.rotate(-35)
            canvas.translate(-PAGE_WIDTH / 2, -PAGE_HEIGHT / 2)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        y = MARGIN - 4 * mm
        canvas.drawString(MARGIN, y, f"{footer_left}  |  Generated on {format_date(generated_on)}")
        canvas.drawCentredString(PAGE_WIDTH / 2, y - 9, "This is a computer-generated document.")
        canvas.drawRightString(PAGE_WIDTH - MARGIN, y, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    return decorate
