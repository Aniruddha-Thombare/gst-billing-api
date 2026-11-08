from decimal import Decimal

import pytest

from app.domain.document_format import (
    amount_in_words,
    format_inr,
    format_plain,
    safe_filename,
)
from app.domain.pdf_rules import document_title, is_void, unprintable_reason


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", "0.00"),
        ("5", "5.00"),
        ("999.5", "999.50"),
        ("1000", "1,000.00"),
        ("100000", "1,00,000.00"),
        ("1234567.5", "12,34,567.50"),
        ("123456789.99", "12,34,56,789.99"),
        ("-1500.5", "-1,500.50"),
        ("0.005", "0.01"),  # half-up, display only
    ],
)
def test_format_inr_uses_indian_grouping(value, expected):
    assert format_inr(Decimal(value)) == expected


@pytest.mark.parametrize(
    ("value", "min_places", "expected"),
    [
        ("2.500", 0, "2.5"),
        ("100.000", 0, "100"),
        ("425.5000", 2, "425.50"),
        ("1890.00", 2, "1890.00"),
        ("99.9999", 2, "99.9999"),  # never rounds a stored rate
        ("9", 0, "9"),
        ("2.5", 0, "2.5"),
    ],
)
def test_format_plain_never_rounds(value, min_places, expected):
    assert format_plain(Decimal(value), min_places) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", "Rupees Zero Only"),
        ("1", "Rupees One Only"),
        ("19", "Rupees Nineteen Only"),
        ("21", "Rupees Twenty One Only"),
        ("100", "Rupees One Hundred Only"),
        ("1234.50", "Rupees One Thousand Two Hundred Thirty Four and Fifty Paise Only"),
        ("100000", "Rupees One Lakh Only"),
        ("288000", "Rupees Two Lakh Eighty Eight Thousand Only"),
        ("12345678", "Rupees One Crore Twenty Three Lakh Forty Five Thousand Six Hundred Seventy Eight Only"),
        ("0.75", "Rupees Zero and Seventy Five Paise Only"),
        ("250000000", "Rupees Twenty Five Crore Only"),
        ("1000000000", "Rupees One Hundred Crore Only"),
    ],
)
def test_amount_in_words(value, expected):
    assert amount_in_words(Decimal(value)) == expected


def test_amount_in_words_rejects_negative():
    with pytest.raises(ValueError):
        amount_in_words(Decimal("-1"))


def test_safe_filename_strips_slashes_and_header_unsafe_characters():
    assert safe_filename("INV/2025-26/0001") == "INV-2025-26-0001"
    assert safe_filename('a"b\r\nc; d') == "a-b-c-d"
    assert safe_filename("///") == "document"


def test_drafts_and_purchase_invoices_cannot_be_printed():
    assert unprintable_reason("sales", "draft") is not None
    assert unprintable_reason("purchase", "sent") is not None


@pytest.mark.parametrize("invoice_type", ["sales", "debit_note", "credit_note"])
@pytest.mark.parametrize("status", ["sent", "partial", "paid", "void"])
def test_issued_documents_can_be_printed(invoice_type, status):
    assert unprintable_reason(invoice_type, status) is None


def test_titles_and_void_flag():
    assert document_title("sales") == "TAX INVOICE"
    assert document_title("credit_note") == "CREDIT NOTE"
    assert is_void("void") and not is_void("sent")
