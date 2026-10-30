"""
GSTR-1 repository — READ ONLY. The only layer that touches the database
for this report.

Contract:
  * every query filters on tenant_id (including each joined table);
  * nothing here inserts, updates, deletes, flushes or commits;
  * no business rules: classification and signing live in domain/gstr1_rules.py.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import and_, case, func, literal_column, or_, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain.gstr1_rules import (
    CANCELLED_STATUSES,
    OUTWARD_NOTE_TYPES,
    REPORTABLE_STATUSES,
)
from app.models.enum import InvoiceStatus, InvoiceType
from app.models.invoice import Invoice
from app.models.invoice_item import InvoiceItem
from app.models.party import Party
from app.models.tenant import Tenant

_SALES = InvoiceType.SALES.value
_CREDIT_NOTE = InvoiceType.CREDIT_NOTE.value


def outward_scope(original: Any) -> Any:
    """
    Outward documents only: sales invoices, plus credit/debit notes whose
    ORIGINAL invoice is a sales invoice. `original` is the aliased Invoice
    joined through original_invoice_id.
    """
    return or_(
        Invoice.invoice_type == _SALES,
        and_(
            Invoice.invoice_type.in_(OUTWARD_NOTE_TYPES),
            original.invoice_type == _SALES,
        ),
    )


async def get_tenant_profile(db: AsyncSession, *, tenant_id: UUID) -> RowMapping | None:
    result = await db.execute(
        select(
            Tenant.id,
            Tenant.gstin,
            Tenant.legal_name,
            Tenant.state_code,
            Tenant.registration_type,
        ).where(Tenant.id == tenant_id)
    )
    return result.mappings().first()


async def fetch_outward_rate_rows(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    start_date: date,
    end_date: date,
    row_limit: int,
) -> Sequence[RowMapping]:
    """
    One row per (document, GST rate) for every reportable outward document in
    the period. Sums come from the STORED line-item tax amounts.

    Returns at most row_limit + 1 rows; the caller treats row_limit + 1 as
    "too large" instead of silently truncating a statutory report.
    """
    original = aliased(Invoice)
    stmt = (
        select(
            Invoice.id.label("invoice_id"),
            Invoice.invoice_number,
            Invoice.invoice_type,
            Invoice.invoice_date,
            Invoice.party_gstin,
            Party.name.label("party_name"),
            Invoice.place_of_supply,
            Invoice.supply_type,
            Invoice.reverse_charge,
            Invoice.total_amount.label("invoice_value"),
            original.invoice_number.label("original_invoice_number"),
            original.invoice_date.label("original_invoice_date"),
            original.total_amount.label("original_invoice_value"),
            InvoiceItem.gst_rate,
            func.sum(InvoiceItem.taxable_amount).label("taxable_amount"),
            func.sum(InvoiceItem.igst_amount).label("igst_amount"),
            func.sum(InvoiceItem.cgst_amount).label("cgst_amount"),
            func.sum(InvoiceItem.sgst_amount).label("sgst_amount"),
            func.sum(InvoiceItem.cess_amount).label("cess_amount"),
        )
        .select_from(Invoice)
        .join(
            InvoiceItem,
            and_(
                InvoiceItem.invoice_id == Invoice.id,
                InvoiceItem.tenant_id == Invoice.tenant_id,
            ),
        )
        .join(
            Party,
            and_(Party.id == Invoice.party_id, Party.tenant_id == Invoice.tenant_id),
        )
        .outerjoin(
            original,
            and_(
                original.id == Invoice.original_invoice_id,
                original.tenant_id == Invoice.tenant_id,
            ),
        )
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.invoice_date >= start_date,
            Invoice.invoice_date <= end_date,
            Invoice.invoice_status.in_(REPORTABLE_STATUSES),
            outward_scope(original),
        )
        .group_by(
            Invoice.id,
            Invoice.invoice_number,
            Invoice.invoice_type,
            Invoice.invoice_date,
            Invoice.party_gstin,
            Party.name,
            Invoice.place_of_supply,
            Invoice.supply_type,
            Invoice.reverse_charge,
            Invoice.total_amount,
            original.invoice_number,
            original.invoice_date,
            original.total_amount,
            InvoiceItem.gst_rate,
        )
        .order_by(Invoice.invoice_date, Invoice.invoice_number, InvoiceItem.gst_rate)
        .limit(row_limit + 1)
    )
    result = await db.execute(stmt)
    return result.mappings().all()


async def fetch_hsn_rows(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    start_date: date,
    end_date: date,
) -> Sequence[RowMapping]:
    """
    Table 12 aggregation done in the database: one row per (HSN/SAC, unit, rate),
    NET of credit notes (quantity and amounts of credit-note lines are negated).
    """
    original = aliased(Invoice)
    # literal_column keeps -1 / 1 / '' as SQL literals. As bind parameters,
    # Postgres would type the CASE branches as text and reject quantity * text.
    credit_note_sign = case(
        (Invoice.invoice_type == _CREDIT_NOTE, literal_column("-1")),
        else_=literal_column("1"),
    )

    def _signed(column: Any) -> Any:
        return func.sum(column * credit_note_sign)

    stmt = (
        select(
            func.coalesce(InvoiceItem.hsn_sac_code, literal_column("''")).label("hsn_sac_code"),
            InvoiceItem.unit,
            InvoiceItem.gst_rate,
            _signed(InvoiceItem.quantity).label("quantity"),
            _signed(InvoiceItem.total_amount).label("total_value"),
            _signed(InvoiceItem.taxable_amount).label("taxable_amount"),
            _signed(InvoiceItem.igst_amount).label("igst_amount"),
            _signed(InvoiceItem.cgst_amount).label("cgst_amount"),
            _signed(InvoiceItem.sgst_amount).label("sgst_amount"),
            _signed(InvoiceItem.cess_amount).label("cess_amount"),
        )
        .select_from(Invoice)
        .join(
            InvoiceItem,
            and_(
                InvoiceItem.invoice_id == Invoice.id,
                InvoiceItem.tenant_id == Invoice.tenant_id,
            ),
        )
        .outerjoin(
            original,
            and_(
                original.id == Invoice.original_invoice_id,
                original.tenant_id == Invoice.tenant_id,
            ),
        )
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.invoice_date >= start_date,
            Invoice.invoice_date <= end_date,
            Invoice.invoice_status.in_(REPORTABLE_STATUSES),
            outward_scope(original),
        )
        .group_by(
            func.coalesce(InvoiceItem.hsn_sac_code, literal_column("''")),
            InvoiceItem.unit,
            InvoiceItem.gst_rate,
        )
        .order_by(
            func.coalesce(InvoiceItem.hsn_sac_code, literal_column("''")),
            InvoiceItem.gst_rate,
        )
    )
    result = await db.execute(stmt)
    return result.mappings().all()


async def fetch_numbered_documents(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    start_date: date,
    end_date: date,
    row_limit: int,
) -> Sequence[RowMapping]:
    """
    (invoice_type, invoice_number, invoice_status) for every outward document
    in the period that holds a legal number: reportable AND cancelled/void.
    Drafts are excluded. Feeds the Table 13 document summary.
    """
    original = aliased(Invoice)
    stmt = (
        select(Invoice.invoice_type, Invoice.invoice_number, Invoice.invoice_status)
        .select_from(Invoice)
        .outerjoin(
            original,
            and_(
                original.id == Invoice.original_invoice_id,
                original.tenant_id == Invoice.tenant_id,
            ),
        )
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.invoice_date >= start_date,
            Invoice.invoice_date <= end_date,
            Invoice.invoice_status.in_(REPORTABLE_STATUSES + CANCELLED_STATUSES),
            outward_scope(original),
        )
        .order_by(Invoice.invoice_date, Invoice.invoice_number)
        .limit(row_limit + 1)
    )
    result = await db.execute(stmt)
    return result.mappings().all()


async def count_draft_documents(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    start_date: date,
    end_date: date,
) -> int:
    """Outward drafts dated inside the period: they are NOT in the return yet."""
    original = aliased(Invoice)
    stmt = (
        select(func.count(Invoice.id))
        .select_from(Invoice)
        .outerjoin(
            original,
            and_(
                original.id == Invoice.original_invoice_id,
                original.tenant_id == Invoice.tenant_id,
            ),
        )
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.invoice_date >= start_date,
            Invoice.invoice_date <= end_date,
            Invoice.invoice_status == InvoiceStatus.DRAFT.value,
            outward_scope(original),
        )
    )
    result = await db.execute(stmt)
    return int(result.scalar_one())
