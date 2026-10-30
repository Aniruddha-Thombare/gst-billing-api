"""
Sales-summary repository — READ ONLY. One query: per (day, document type)
counts and sums from STORED line-item amounts. Bucketing into weeks / months /
quarters / years is a domain rule (domain/sales_summary_rules.py), not SQL.
"""

from __future__ import annotations

from datetime import date
from typing import Sequence
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain.gstr1_rules import REPORTABLE_STATUSES
from app.models.invoice import Invoice
from app.models.invoice_item import InvoiceItem
from app.repositories.gstr1_repository import outward_scope


async def fetch_daily_sales(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    start_date: date,
    end_date: date,
) -> Sequence[RowMapping]:
    original = aliased(Invoice)
    stmt = (
        select(
            Invoice.invoice_date,
            Invoice.invoice_type,
            func.count(func.distinct(Invoice.id)).label("document_count"),
            func.sum(InvoiceItem.total_amount).label("total_value"),
            func.sum(InvoiceItem.taxable_amount).label("taxable_amount"),
            func.sum(
                InvoiceItem.igst_amount
                + InvoiceItem.cgst_amount
                + InvoiceItem.sgst_amount
                + InvoiceItem.cess_amount
            ).label("tax_amount"),
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
        .group_by(Invoice.invoice_date, Invoice.invoice_type)
        .order_by(Invoice.invoice_date)
    )
    result = await db.execute(stmt)
    return result.mappings().all()
