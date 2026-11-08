import re
from datetime import date, datetime, timezone
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from app.pdf.invoice_document import build_seller
from app.pdf.voucher_document import (
    build_receipt_data,
    build_refund_data,
    build_voucher_buyer,
    mode_label,
)
from app.pdf.voucher_renderer import render_voucher_pdf

_TENANT = SimpleNamespace(
    legal_name="Sharma & Sons Pvt. Ltd.", trade_name=None, gstin="27ABCDE1234F1Z5",
    address_line1="Shop 12, Laxmi Road", address_line2=None, city="Pune", pincode="411002",
    state_code="27", phone=None, email="accounts@sharma.example",
)
_PARTY = SimpleNamespace(
    name="Patel & Co.", address_line1="Plot 45, GIDC", address_line2=None,
    city="Ahmedabad", pincode="380015", phone=None, email=None,
)
_INVOICE = SimpleNamespace(
    invoice_number="INV/2025-26/0001", invoice_date=date(2026, 11, 5),
    total_amount=D("52856.92"), outstanding_amount=D("42856.92"),
)
_TODAY = date(2026, 11, 7)


def _payment(**overrides):
    values = dict(
        payment_number="RCT/2026-27/0007", payment_date=date(2026, 11, 6), amount=D("10000.00"),
        payment_mode="bank_transfer", reference_number="UTR998877", bank_name="HDFC Bank",
        is_realized=True, notes="internal only", status="active", cancelled_at=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _refund(**overrides):
    values = dict(
        refund_number="RFD/2026-27/0002", refund_date=date(2026, 11, 7), amount=D("1250.50"),
        refund_mode="upi", reference_number="UPI123456", bank_name=None, notes="internal",
        status="active", cancelled_at=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _buyer():
    return build_voucher_buyer(_PARTY, gstin="29ABCDE1234F1Z5", state_code="27")


def _printed(pdf: bytes) -> bytes:
    """reportlab emits text in small fragments; join them back for assertions."""
    fragments = re.findall(rb"\(((?:[^()\\]|\\.)*)\) Tj", pdf)  # allows escaped \( \) inside
    return b"".join(fragments).replace(b"\\(", b"(").replace(b"\\)", b")")


def _receipt(**overrides) -> bytes:
    data = build_receipt_data(
        payment=_payment(**overrides), invoice=_INVOICE, seller=build_seller(_TENANT),
        buyer=_buyer(), generated_on=_TODAY,
    )
    return render_voucher_pdf(data, compress=False)


def _refund_pdf(**overrides) -> bytes:
    data = build_refund_data(
        refund=_refund(**overrides), invoice=_INVOICE, seller=build_seller(_TENANT),
        buyer=_buyer(), generated_on=_TODAY,
    )
    return render_voucher_pdf(data, compress=False)


def test_receipt_prints_the_stored_facts():
    pdf = _receipt()
    printed = _printed(pdf)
    assert pdf.startswith(b"%PDF") and pdf.rstrip().endswith(b"%%EOF")
    for fact in (b"PAYMENT RECEIPT", b"RCT/2026-27/0007", b"Amount received (INR)", b"10,000.00", b"Bank Transfer",
                 b"UTR998877", b"HDFC Bank", b"INV/2025-26/0001", b"52,856.92", b"42,856.92",
                 b"Rupees Ten Thousand Only", b"29ABCDE1234F1Z5"):
        assert fact in printed, fact


def test_internal_notes_are_never_printed():
    assert b"internal only" not in _printed(_receipt())
    assert b"internal" not in _printed(_refund_pdf())


def test_unrealised_cheque_is_marked_subject_to_realisation():
    printed = _printed(_receipt(payment_mode="cheque", is_realized=False))
    assert b"Subject to realisation of the cheque." in printed


def test_realised_cheque_and_cash_carry_no_realisation_remark():
    assert b"Subject to realisation" not in _printed(_receipt(payment_mode="cheque", is_realized=True))
    assert b"Subject to realisation" not in _printed(
        _receipt(payment_mode="cash", is_realized=False, reference_number=None, bank_name=None)
    )


def test_cancelled_payment_is_watermarked_and_says_so():
    pdf = _receipt(status="cancelled", cancelled_at=datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc))
    printed = _printed(pdf)
    assert b"CANCELLED" in printed
    assert b"on 07-11-2026" in printed  # 20:00 UTC on the 6th is 01:30 IST on the 7th


def test_active_document_has_no_cancelled_text():
    assert b"CANCELLED" not in _printed(_receipt())


def test_refund_voucher_prints_refund_facts():
    printed = _printed(_refund_pdf())
    for fact in (b"REFUND VOUCHER", b"RFD/2026-27/0002", b"1,250.50", b"UPI", b"UPI123456",
                 b"Refunded to", b"Amount refunded (INR)",
                 b"Rupees One Thousand Two Hundred Fifty and Fifty Paise Only"):
        assert fact in printed, fact


def test_cancelled_refund_is_watermarked():
    printed = _printed(_refund_pdf(status="cancelled", cancelled_at=datetime(2026, 11, 7, 6, 0, tzinfo=timezone.utc)))
    assert b"CANCELLED" in printed


@pytest.mark.parametrize(
    ("raw", "label"),
    [("cash", "Cash"), ("bank_transfer", "Bank Transfer"), ("upi", "UPI"),
     ("cheque", "Cheque"), ("credit_card", "Credit Card")],
)
def test_mode_labels(raw, label):
    assert mode_label(raw) == label
