"""
Which invoices may be printed, and under what document title. Pure rules.
"""

from app.models.enum import InvoiceType

# Documents WE issue. A purchase invoice is the vendor's document, not ours.
DOCUMENT_TITLES: dict[str, str] = {
    InvoiceType.SALES.value: "TAX INVOICE",
    InvoiceType.DEBIT_NOTE.value: "DEBIT NOTE",
    InvoiceType.CREDIT_NOTE.value: "CREDIT NOTE",
}

_DRAFT = "draft"
_VOID = "void"


def _plain(value: object) -> str:
    """Works for both a str and a (str, Enum) member."""
    return str(getattr(value, "value", value))


def unprintable_reason(invoice_type: object, invoice_status: object) -> str | None:
    """None when the invoice may be printed, otherwise the reason (shown to the caller)."""
    if _plain(invoice_type) not in DOCUMENT_TITLES:
        return "Only sales invoices, debit notes and credit notes can be downloaded as PDF."
    if _plain(invoice_status) == _DRAFT:
        return "A draft is not a legal document yet. Send the invoice first, then download the PDF."
    return None


def is_void(invoice_status: object) -> bool:
    return _plain(invoice_status) == _VOID


def document_title(invoice_type: object) -> str:
    return DOCUMENT_TITLES[_plain(invoice_type)]
