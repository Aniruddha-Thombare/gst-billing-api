"""Builds the downloadable PDF for one payment receipt or refund voucher. Read-only."""

import asyncio
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DocumentNotFoundError
from app.domain.document_format import safe_filename
from app.pdf.common import PdfDocument
from app.pdf.invoice_document import SellerBlock, build_seller
from app.pdf.voucher_document import (
    VoucherPdfData,
    build_receipt_data,
    build_refund_data,
    build_voucher_buyer,
)
from app.pdf.voucher_renderer import render_voucher_pdf
from app.repositories import pdf_data_repository, voucher_data_repository
from app.services.report_common import today_ist

logger = logging.getLogger(__name__)


async def _load_invoice_context(db: AsyncSession, *, tenant_id: UUID, invoice_id: UUID):
    """(invoice summary row, seller block, buyer block) for the invoice a voucher refers to."""
    invoice = await voucher_data_repository.get_invoice_summary(
        db, tenant_id=tenant_id, invoice_id=invoice_id
    )
    if invoice is None:  # impossible while invoice_id is a RESTRICT foreign key
        raise DocumentNotFoundError("Invoice", str(invoice_id))
    tenant = await pdf_data_repository.get_tenant(db, tenant_id=tenant_id)
    if tenant is None:  # impossible for a valid token: tenant_id comes from the JWT
        raise RuntimeError(f"Tenant {tenant_id} not found while building a voucher PDF")
    party = await pdf_data_repository.get_party(db, tenant_id=tenant_id, party_id=invoice.party_id)
    if party is None:  # impossible while parties.id is a RESTRICT foreign key
        raise DocumentNotFoundError("Party", str(invoice.party_id))
    seller: SellerBlock = build_seller(tenant)
    buyer = build_voucher_buyer(
        party, gstin=invoice.party_gstin, state_code=invoice.party_state_code
    )
    return invoice, seller, buyer


async def _render(data: VoucherPdfData) -> PdfDocument:
    # reportlab is synchronous and CPU-bound: keep it off the event loop.
    content = await asyncio.to_thread(render_voucher_pdf, data)
    logger.info(
        "voucher_pdf_generated",
        extra={"document": data.title, "number": data.number, "pdf_bytes": len(content)},
    )
    return PdfDocument(content=content, filename=f"{safe_filename(data.number)}.pdf")


async def generate_payment_receipt_pdf(
    db: AsyncSession, *, payment_id: UUID, tenant_id: UUID
) -> PdfDocument:
    payment = await voucher_data_repository.get_payment(
        db, tenant_id=tenant_id, payment_id=payment_id
    )
    if payment is None:  # missing OR another tenant's: same 404, nothing leaks
        raise DocumentNotFoundError("Payment", str(payment_id))
    invoice, seller, buyer = await _load_invoice_context(
        db, tenant_id=tenant_id, invoice_id=payment.invoice_id
    )
    data = build_receipt_data(
        payment=payment, invoice=invoice, seller=seller, buyer=buyer, generated_on=today_ist()
    )
    return await _render(data)


async def generate_refund_voucher_pdf(
    db: AsyncSession, *, refund_id: UUID, tenant_id: UUID
) -> PdfDocument:
    refund = await voucher_data_repository.get_refund(db, tenant_id=tenant_id, refund_id=refund_id)
    if refund is None:
        raise DocumentNotFoundError("Refund", str(refund_id))
    invoice, seller, buyer = await _load_invoice_context(
        db, tenant_id=tenant_id, invoice_id=refund.invoice_id
    )
    data = build_refund_data(
        refund=refund, invoice=invoice, seller=seller, buyer=buyer, generated_on=today_ist()
    )
    return await _render(data)
