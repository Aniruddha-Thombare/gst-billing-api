"""Builds the downloadable PDF for one invoice. Read-only: nothing is written."""

import asyncio
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvoicePdfNotAvailableError, PartyNotFoundError
from app.domain.document_format import safe_filename
from app.domain.pdf_rules import unprintable_reason
from app.pdf.common import PdfDocument
from app.pdf.invoice_document import (
    InvoicePdfData,
    OriginalInvoiceRef,
    build_buyer,
    build_seller,
)
from app.pdf.invoice_renderer import render_invoice_pdf
from app.repositories import pdf_data_repository
from app.schemas.invoice import InvoiceResponse
from app.services import invoice_service
from app.services.report_common import today_ist

logger = logging.getLogger(__name__)


async def _load_original_ref(
    db: AsyncSession, *, tenant_id: UUID, invoice: InvoiceResponse
) -> OriginalInvoiceRef | None:
    if invoice.original_invoice_id is None:
        return None
    row = await pdf_data_repository.get_invoice_reference(
        db, tenant_id=tenant_id, invoice_id=invoice.original_invoice_id
    )
    if row is None:
        return None
    return OriginalInvoiceRef(invoice_number=row.invoice_number, invoice_date=row.invoice_date)


async def _load_pdf_data(
    db: AsyncSession, *, tenant_id: UUID, invoice: InvoiceResponse
) -> InvoicePdfData:
    tenant = await pdf_data_repository.get_tenant(db, tenant_id=tenant_id)
    if tenant is None:  # impossible for a valid token: tenant_id comes from the JWT
        raise RuntimeError(f"Tenant {tenant_id} not found while building an invoice PDF")
    party = await pdf_data_repository.get_party(db, tenant_id=tenant_id, party_id=invoice.party_id)
    if party is None:  # impossible while parties.id is a RESTRICT foreign key
        raise PartyNotFoundError(str(invoice.party_id))
    return InvoicePdfData(
        invoice=invoice,
        seller=build_seller(tenant),
        buyer=build_buyer(party, invoice),
        original=await _load_original_ref(db, tenant_id=tenant_id, invoice=invoice),
        generated_on=today_ist(),
    )


async def generate_invoice_pdf(
    db: AsyncSession, *, invoice_id: UUID, tenant_id: UUID
) -> PdfDocument:
    # 404 for a missing invoice or another tenant's invoice (same rule as GET /invoices/{id}).
    fetched = await invoice_service.fetch_invoice(db, invoice_id=invoice_id, tenant_id=tenant_id)
    invoice = InvoiceResponse.model_validate(fetched)

    reason = unprintable_reason(invoice.invoice_type, invoice.invoice_status)
    if reason is not None:
        raise InvoicePdfNotAvailableError(reason)

    data = await _load_pdf_data(db, tenant_id=tenant_id, invoice=invoice)
    # reportlab is synchronous and CPU-bound: keep it off the event loop.
    content = await asyncio.to_thread(render_invoice_pdf, data)
    logger.info(
        "invoice_pdf_generated",
        extra={"invoice_id": str(invoice.id), "pdf_bytes": len(content)},
    )
    return PdfDocument(content=content, filename=f"{safe_filename(invoice.invoice_number)}.pdf")
