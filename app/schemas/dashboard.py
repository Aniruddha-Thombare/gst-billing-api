from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class ReceivablesWidget(BaseModel):
    total_outstanding: Decimal
    open_invoices: int
    overdue_outstanding: Decimal
    overdue_invoices: int


class RefundsDueWidget(BaseModel):
    total_refund_due: Decimal
    invoices_with_refund_due: int


class MonthSalesWidget(BaseModel):
    taxable_amount: Decimal
    gst_amount: Decimal
    total_amount: Decimal


class CollectionsWidget(BaseModel):
    total_collected: Decimal
    payments_count: int


class TopCustomer(BaseModel):
    party_id: UUID
    party_name: str
    outstanding: Decimal
    open_invoices: int


class DashboardResponse(BaseModel):
    as_of: datetime
    today: date
    month_start: date
    month_end: date
    receivables: ReceivablesWidget
    refunds_due: RefundsDueWidget
    sales_this_month: MonthSalesWidget
    collections_this_month: CollectionsWidget
    sales_invoice_counts_by_status: dict[str, int]
    top_customers_by_outstanding: list[TopCustomer]