import re
from datetime import date, datetime, timezone
from decimal import Decimal as D
from types import SimpleNamespace
from uuid import uuid4

from app.pdf.invoice_document import (
    InvoicePdfData,
    OriginalInvoiceRef,
    build_buyer,
    build_seller,
)
from app.pdf.invoice_renderer import render_invoice_pdf
from app.schemas.invoice import InvoiceResponse, LineItemResponse

_TENANT = SimpleNamespace(
    legal_name="Sharma & Sons Pvt. Ltd.", trade_name=None, gstin="27ABCDE1234F1Z5",
    address_line1="Shop 12, Laxmi Road", address_line2=None, city="Pune", pincode="411002",
    state_code="27", phone=None, email="accounts@sharma.example",
)
_PARTY = SimpleNamespace(
    name="Patel <Electronics> & Co.", address_line1="Plot 45, GIDC", address_line2=None,
    city="Ahmedabad", pincode="380015", phone=None, email=None,
)


def _line(number: int = 1, *, description: str = "LED Panel", intra: bool = True) -> LineItemResponse:
    # 2 x 100.00 @ 18% -> taxable 200.00, tax 36.00, total 236.00
    return LineItemResponse(
        id=uuid4(), line_number=number, description=description, hsn_sac_code="94054090",
        quantity=D("2"), unit="NOS", rate=D("100.0000"), discount_percent=D("0"),
        discount_amount=D("0.00"), taxable_amount=D("200.00"), gst_rate=D("18"),
        cgst_rate=D("9") if intra else D("0"), sgst_rate=D("9") if intra else D("0"),
        igst_rate=D("0") if intra else D("18"),
        cgst_amount=D("18.00") if intra else D("0.00"), sgst_amount=D("18.00") if intra else D("0.00"),
        igst_amount=D("0.00") if intra else D("36.00"),
        cess_rate=D("0"), cess_amount=D("0.00"), total_amount=D("236.00"),
    )


def _invoice(lines=None, *, intra=True, invoice_type="sales", status="sent", paid="0") -> InvoiceResponse:
    lines = lines or [_line(intra=intra)]
    count = len(lines)
    total = D("236.00") * count
    return InvoiceResponse(
        id=uuid4(), tenant_id=uuid4(), invoice_number="INV/2025-26/0001", invoice_type=invoice_type,
        invoice_date=date(2026, 11, 5), due_date=date(2026, 12, 5), financial_year="2026-27",
        party_id=uuid4(), party_gstin="29ABCDE1234F1Z5", party_state_code="27",
        supply_type="intrastate" if intra else "interstate", place_of_supply="27", reverse_charge=False,
        subtotal=D("200.00") * count, discount_amount=D("0.00"), taxable_amount=D("200.00") * count,
        cgst_amount=D("18.00") * count if intra else D("0.00"),
        sgst_amount=D("18.00") * count if intra else D("0.00"),
        igst_amount=D("0.00") if intra else D("36.00") * count, cess_amount=D("0.00"),
        total_amount=total, paid_amount=D(paid), credited_amount=D("0"), refunded_amount=D("0"),
        outstanding_amount=total - D(paid), refund_due_amount=D("0"), invoice_status=status,
        notes=None, terms=None, original_invoice_id=None, is_locked=True, locked_at=None,
        voided_at=None, voided_by=None, void_reason=None,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc), line_items=lines,
    )


def _render(invoice: InvoiceResponse, original=None, *, compress=False) -> bytes:
    data = InvoicePdfData(
        invoice=invoice, seller=build_seller(_TENANT), buyer=build_buyer(_PARTY, invoice),
        original=original, generated_on=date(2026, 11, 7),
    )
    return render_invoice_pdf(data, compress=compress)


def test_output_is_a_pdf_with_the_stored_numbers():
    pdf = _render(_invoice(paid="36"))
    assert pdf.startswith(b"%PDF") and pdf.rstrip().endswith(b"%%EOF")
    for printed in (b"INV/2025-26/0001", b"236.00", b"200.00", b"Rupees Two Hundred Thirty Six Only",
                    b"27ABCDE1234F1Z5", b"Balance due", b"200.00"):
        assert printed in pdf


def test_user_text_with_markup_characters_does_not_break_the_render():
    pdf = _render(_invoice([_line(description="A&B <3m> 'x'")]))
    assert pdf.startswith(b"%PDF")
    # reportlab emits text in small fragments: (A) Tj (&) Tj (B <) Tj ... join them back.
    printed = b"".join(re.findall(rb"\(([^()]*)\) Tj", pdf))
    assert b"A&B <3m> 'x'" in printed  # escaped on the way in, printed literally


def test_interstate_invoice_prints_igst_not_cgst_sgst():
    pdf = _render(_invoice(intra=False))
    assert b"IGST" in pdf and b"CGST" not in pdf and b"SGST" not in pdf


def test_intrastate_invoice_prints_cgst_and_sgst():
    pdf = _render(_invoice(intra=True))
    assert b"CGST" in pdf and b"SGST" in pdf and b"IGST" not in pdf


def test_credit_note_has_title_reference_and_no_balance_due():
    credit_note = _invoice(invoice_type="credit_note")
    pdf = _render(credit_note, OriginalInvoiceRef("INV/2025-26/0009", date(2026, 11, 1)))
    assert b"CREDIT NOTE" in pdf
    assert b"Against invoice: INV/2025-26/0009" in pdf
    assert b"Balance due" not in pdf and b"Due date" not in pdf


def test_void_invoice_is_watermarked_and_shows_no_balance_due():
    pdf = _render(_invoice(status="void"))
    assert b"VOID" in pdf
    assert b"Balance due" not in pdf


def test_hundred_line_invoice_renders_on_several_pages():
    lines = [_line(number, description=f"Item {number} with a long description " * 3) for number in range(1, 101)]
    pdf = _render(_invoice(lines))
    assert len(re.findall(rb"/Type /Page(?!s)", pdf)) >= 3


def test_compressed_output_is_smaller_and_still_a_pdf():
    invoice = _invoice([_line(number) for number in range(1, 30)])
    assert len(_render(invoice, compress=True)) < len(_render(invoice, compress=False))
    assert _render(invoice, compress=True).startswith(b"%PDF")
