from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ( CheckConstraint, Date, DateTime, ForeignKey, Index, 
                    Numeric, String, Text, UniqueConstraint )
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.models.base import BaseModel


class Refund(BaseModel):
    """
    Cash returned to a customer against an invoice (a payment in reverse).
    Never deleted: status='cancelled' keeps the row for audit. The amount
    still owed to the customer is DERIVED (invoices.refund_due_amount),
    not stored here; this table records only payouts that actually happened.
    """
    __tablename__ = "refunds"
    __mapper_args__ = {"eager_defaults": True}

    __table_args__ = (
        CheckConstraint("amount > 0", name="check_refunds_amount_positive"),
        CheckConstraint("status IN ('active', 'cancelled')", name="check_refunds_status"),
        CheckConstraint(
            "refund_mode IN ('cash', 'bank_transfer', 'upi', 'cheque', 'credit_card')",
            name="check_refunds_refund_mode",
        ),
        CheckConstraint(
            "refund_mode = 'cash' OR reference_number IS NOT NULL",
            name="check_refund_reference_required_for_non_cash",
        ),
        UniqueConstraint("tenant_id", "refund_number", name="uq_refunds_tenant_number"),
        Index(
            "uq_refunds_tenant_refnum", "tenant_id", "reference_number", unique=True,
            postgresql_where=text("reference_number IS NOT NULL AND status = 'active'"),
        ),
        Index("idx_refunds_tenant_invoice", "tenant_id", "invoice_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), 
        ForeignKey("tenants.id", ondelete="RESTRICT"), 
        nullable=False
    )
    
    invoice_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), 
        ForeignKey("invoices.id", ondelete="RESTRICT"), 
        nullable=False
    )

    refund_number: Mapped[str] = mapped_column(String(50), nullable=False)

    refund_date: Mapped[date] = mapped_column(Date, nullable=False)

    amount: Mapped[Decimal] = mapped_column(Numeric(17, 2), nullable=False)

    refund_mode: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'cash'")
    )

    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'active'")
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    cancelled_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), 
        ForeignKey("users.id", ondelete="SET NULL"), 
        nullable=True
    )

    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), 
        ForeignKey("users.id", ondelete="SET NULL"), 
        nullable=True
    )