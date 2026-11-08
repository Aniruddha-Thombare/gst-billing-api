"""
Plain data the invoice renderer needs. The renderer never touches the DB:
the service loads rows, these builders turn them into frozen dataclasses.
"""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.schemas.invoice import InvoiceResponse


class _Addressable(Protocol):
    address_line1: str
    address_line2: str | None
    city: str
    pincode: str


def build_address_lines(row: _Addressable) -> tuple[str, ...]:
    lines = [row.address_line1.strip()]
    if row.address_line2 and row.address_line2.strip():
        lines.append(row.address_line2.strip())
    lines.append(f"{row.city.strip()} - {row.pincode}")
    return tuple(lines)


@dataclass(frozen=True)
class SellerBlock:
    legal_name: str
    trade_name: str | None
    gstin: str
    address_lines: tuple[str, ...]
    state_code: str
    phone: str | None
    email: str | None


@dataclass(frozen=True)
class BuyerBlock:
    name: str
    address_lines: tuple[str, ...]
    gstin: str | None  # the GSTIN frozen on the invoice, not the party's current one
    state_code: str  # frozen on the invoice as well
    phone: str | None
    email: str | None


@dataclass(frozen=True)
class OriginalInvoiceRef:
    invoice_number: str
    invoice_date: date


@dataclass(frozen=True)
class InvoicePdfData:
    invoice: InvoiceResponse
    seller: SellerBlock
    buyer: BuyerBlock
    original: OriginalInvoiceRef | None
    generated_on: date


class _TenantRow(_Addressable, Protocol):
    legal_name: str
    trade_name: str | None
    gstin: str
    state_code: str
    phone: str | None
    email: str


class _PartyRow(_Addressable, Protocol):
    name: str
    phone: str | None
    email: str | None


def build_seller(tenant: _TenantRow) -> SellerBlock:
    return SellerBlock(
        legal_name=tenant.legal_name,
        trade_name=tenant.trade_name,
        gstin=tenant.gstin,
        address_lines=build_address_lines(tenant),
        state_code=tenant.state_code,
        phone=tenant.phone,
        email=tenant.email,
    )


def build_buyer(party: _PartyRow, invoice: InvoiceResponse) -> BuyerBlock:
    """Name/address come from the party master; GSTIN and state from the invoice snapshot."""
    return BuyerBlock(
        name=party.name,
        address_lines=build_address_lines(party),
        gstin=invoice.party_gstin,
        state_code=invoice.party_state_code,
        phone=party.phone,
        email=party.email,
    )
