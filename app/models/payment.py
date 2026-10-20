from __future__ import annotations
from uuid import UUID
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from sqlalchemy.sql import text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy import (
    Boolean, String, Numeric, Index, CheckConstraint, ForeignKey,
    Date, DateTime, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import BaseModel
from app.models.enum import PaymentMode

if TYPE_CHECKING:
    from app.models.tenant import Tenant
    from app.models.invoice import Invoice
    from app.models.user import User


class Payment(BaseModel):
    """
    Ledger of all payment transactions recorded against invoices.

    Payments are never hard-deleted. A payment recorded in error is
    soft-cancelled (status='cancelled') — the row stays permanently for
    audit, reconciliation, and so its reference_number can be traced by
    the bank team even after cancellation. See status/cancelled_* fields.
    """

    __tablename__ = "payments"

    __mapper_args__ = {"eager_defaults": True}

    __table_args__ = (
        CheckConstraint(
            f"payment_mode IN ({', '.join(repr(e.value) for e in PaymentMode)})",
            name="check_payments_payment_mode"
        ),
        CheckConstraint(
            f"payment_mode NOT IN ({', '.join(repr(e.value) for e in [PaymentMode.CHEQUE, PaymentMode.BANK_TRANSFER])}) "
            f"OR bank_name IS NOT NULL",
            name="check_payment_bank_name_required_for_bank_cheque"
        ),
        CheckConstraint(
            f"payment_mode = '{PaymentMode.CASH.value}' OR reference_number IS NOT NULL",
            name="check_payment_reference_required_for_non_cash"
        ),
        CheckConstraint("amount > 0", name="check_payments_amount_positive"),

        # Status is a small, fixed, stable set — same reasoning as
        # IdempotencyKey.status: worth a DB-level guard against a bug
        # writing a fifth, nonsensical value directly to the table.
        CheckConstraint(
            "status IN ('active', 'cancelled')",
            name="check_payments_status"
        ),

        UniqueConstraint(
            "tenant_id", "payment_number", name="uq_payments_tenant_number"
        ),

        Index("idx_payments_tenant_mode_date", "tenant_id", "payment_mode", "payment_date"),
        Index("idx_payments_invoiceid", "invoice_id"),
        Index(
            "idx_payments_tenant_realized",
            "tenant_id", "is_realized", "payment_date"
        ),

        # Require while displaying the list of payments 
        Index("idx_payments_tenant_date_id", "tenant_id", "payment_date", "id"),

        # UPDATED: now scoped to status='active' too, not just reference_number
        # IS NOT NULL. A cancelled payment's reference number becomes reusable —
        # a new, correct payment can legitimately reuse a real bank reference
        # that was attached to a payment later cancelled for a data-entry error.
        Index(
            "uq_payments_tenant_refnum",
            "tenant_id", "reference_number",
            unique=True,
            postgresql_where=text("reference_number IS NOT NULL AND status = 'active'"),
        ),

        # Fast filtering for cancellation checks and any future "show me
        # active/cancelled payments" listing — same composite-prefix
        # reasoning as idx_payments_tenant_mode_date.
        Index("idx_payments_tenant_status", "tenant_id", "status"),
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

    payment_date: Mapped[date] = mapped_column(Date, nullable=False)

    amount: Mapped[Decimal] = mapped_column(Numeric(17, 2), nullable=False)

    payment_mode: Mapped[PaymentMode] = mapped_column(
        String(30),
        nullable=False,
        server_default=text(f"'{PaymentMode.CASH.value}'")
    )

    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    payment_number: Mapped[str] = mapped_column(String(50), nullable=False)

    is_realized: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false")
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )

    # CANCELLATION FIELDS 
    # status: 'active' (default, counts toward invoice paid_amount) |
    # 'cancelled' (excluded from every SUM/duplicate check, but the row
    # is never deleted — see class docstring).
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active",
        server_default=text("'active'")
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Who performed the cancellation — separate from created_by (who
    # recorded the original payment). Same ondelete="SET NULL" pattern
    # as created_by: losing the user record shouldn't cascade-delete
    # financial audit history.
    cancelled_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )

    # Mandatory at the schema layer (PaymentCancelRequest), nullable here
    # only because it has no value before a payment is ever cancelled.
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        back_populates="payments",
        lazy="noload"
    )

    invoice: Mapped["Invoice"] = relationship(
        "Invoice",
        back_populates="payments",
        lazy="noload"
    )