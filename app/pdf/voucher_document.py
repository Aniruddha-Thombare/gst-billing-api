"""
Plain data for payment receipts and refund vouchers, plus the pure builders
that turn already-loaded rows into that data. No DB, no clock.

Both documents are the same shape (money moved against one invoice), so they
share one dataclass and one renderer.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Protocol

from app.models.enum import PaymentMode
from app.pdf.invoice_document import BuyerBlock, SellerBlock, build_address_lines

# India has no daylight saving, so a fixed offset is exact (and needs no tzdata package).
_IST = timezone(timedelta(hours=5, minutes=30))
_CANCELLED = "cancelled"

_MODE_LABELS = {"upi": "UPI", "neft": "NEFT", "rtgs": "RTGS", "imps": "IMPS"}


def mode_label(mode: object) -> str:
    """'bank_transfer' -> 'Bank Transfer', 'upi' -> 'UPI'."""
    value = str(getattr(mode, "value", mode))
    return _MODE_LABELS.get(value, value.replace("_", " ").title())


def _ist_date(moment: datetime | None) -> date | None:
    return moment.astimezone(_IST).date() if moment else None


class _InvoiceRow(Protocol):
    invoice_number: str
    invoice_date: date
    total_amount: Decimal
    outstanding_amount: Decimal


class _MoneyRow(Protocol):
    amount: Decimal
    reference_number: str | None
    bank_name: str | None
    status: str
    cancelled_at: datetime | None


@dataclass(frozen=True)
class VoucherPdfData:
    title: str  # "PAYMENT RECEIPT" | "REFUND VOUCHER"
    number: str
    voucher_date: date
    party_heading: str  # "Received from" | "Refunded to"
    amount_label: str
    amount: Decimal
    mode: str  # already a display label
    reference_number: str | None
    bank_name: str | None
    remarks: tuple[str, ...]
    invoice_number: str
    invoice_date: date
    invoice_total: Decimal
    invoice_balance: Decimal  # the invoice's STORED outstanding amount, as of generated_on
    seller: SellerBlock
    buyer: BuyerBlock
    cancelled: bool
    cancelled_on: date | None
    generated_on: date


class _PartyRow(Protocol):
    name: str
    address_line1: str
    address_line2: str | None
    city: str
    pincode: str
    phone: str | None
    email: str | None


def build_voucher_buyer(party: _PartyRow, *, gstin: str | None, state_code: str) -> BuyerBlock:
    """Name/address from the party master; GSTIN and state from the invoice snapshot."""
    return BuyerBlock(
        name=party.name,
        address_lines=build_address_lines(party),
        gstin=gstin,
        state_code=state_code,
        phone=party.phone,
        email=party.email,
    )


def _common(
    money: _MoneyRow, invoice: _InvoiceRow, seller: SellerBlock, buyer: BuyerBlock,
    generated_on: date,
) -> dict[str, object]:
    cancelled = money.status == _CANCELLED
    return {
        "amount": money.amount,
        "reference_number": money.reference_number,
        "bank_name": money.bank_name,
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date,
        "invoice_total": invoice.total_amount,
        "invoice_balance": invoice.outstanding_amount,
        "seller": seller,
        "buyer": buyer,
        "cancelled": cancelled,
        "cancelled_on": _ist_date(money.cancelled_at) if cancelled else None,
        "generated_on": generated_on,
    }


class _PaymentRow(_MoneyRow, Protocol):
    payment_number: str
    payment_date: date
    payment_mode: object
    is_realized: bool


class _RefundRow(_MoneyRow, Protocol):
    refund_number: str
    refund_date: date
    refund_mode: str


def build_receipt_data(
    *, payment: _PaymentRow, invoice: _InvoiceRow, seller: SellerBlock, buyer: BuyerBlock,
    generated_on: date,
) -> VoucherPdfData:
    mode_value = str(getattr(payment.payment_mode, "value", payment.payment_mode))
    remarks: list[str] = []
    if mode_value == PaymentMode.CHEQUE.value and not payment.is_realized:
        remarks.append("Subject to realisation of the cheque.")
    # payment.notes is deliberately NOT printed: it is an internal field.
    return VoucherPdfData(
        title="PAYMENT RECEIPT",
        number=payment.payment_number,
        voucher_date=payment.payment_date,
        party_heading="Received from",
        amount_label="Amount received (INR)",
        mode=mode_label(mode_value),
        remarks=tuple(remarks),
        **_common(payment, invoice, seller, buyer, generated_on),  # type: ignore[arg-type]
    )


def build_refund_data(
    *, refund: _RefundRow, invoice: _InvoiceRow, seller: SellerBlock, buyer: BuyerBlock,
    generated_on: date,
) -> VoucherPdfData:
    return VoucherPdfData(
        title="REFUND VOUCHER",
        number=refund.refund_number,
        voucher_date=refund.refund_date,
        party_heading="Refunded to",
        amount_label="Amount refunded (INR)",
        mode=mode_label(refund.refund_mode),
        remarks=(),
        **_common(refund, invoice, seller, buyer, generated_on),  # type: ignore[arg-type]
    )
