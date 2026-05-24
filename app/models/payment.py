from __future__ import annotations
from uuid import UUID 
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from sqlalchemy.sql import text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy import Boolean, String, Numeric, Index, CheckConstraint, ForeignKey, Date, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import BaseModel
from app.models.enum import PaymentMode

# Importing models for python level Mapping
if TYPE_CHECKING:
    from app.models.tenant import Tenant
    from app.models.invoice import Invoice


class Payment(BaseModel):
    """
    Ledger of all payment transactions recorded against invoices.
    It acts as a record book of every time money is received or paid for an invoice.

    It doesn't care about the direction of the money on its own, it relies entirely
    on the linked Invoice to provide that context. 

    In accounting, you cannot simply change the "Paid" status on an invoice without 
    proof. This table provides that proof by storing the date, when it happened, 
    the exact amount, and the transaction references (like UPI ID or cheque number)
    for every rupee that moves.

    """
    
    __tablename__ = "payments"

    # This tells SQLAlchemy: "For this entire table, fetch all DB defaults on save"
    __mapper_args__ = {"eager_defaults": True}

    __table_args__ = (

        # Enum constraints - Database level validation
        # Ensures Database rejects any value which is not explicitly defined in the Enum class
        CheckConstraint(
            f"payment_mode IN ({', '.join(repr(e.value) for e in PaymentMode)})",
            name="check_payments_payment_mode"
        ),
        # To check bank_name is provided for payments done via cheque or bank transfer
        CheckConstraint(
            f"payment_mode NOT IN ({', '.join(repr(e.value) for e in [PaymentMode.CHEQUE, PaymentMode.BANK_TRANSFER])}) "
            f"OR bank_name IS NOT NULL",
            name="check_payment_bank_name_required_for_bank_cheque"
        ),

        # Reference number should not be equal to null for non cash transactions
        CheckConstraint(
            f"payment_mode = '{PaymentMode.CASH.value}' OR reference_number IS NOT NULL",
            name="check_payment_reference_required_for_non_cash"
        ),

        # To avoid any accidental negative amount entries 
        CheckConstraint("amount > 0", name="check_payments_amount_positive"),

        # Daily Collection Reports 
        # This composite index allows DB to instantly filter by Tenant, Payment mode,
        # and Date without scanning the entire table 
        Index("idx_payments_tenant_mode_date", "tenant_id", "payment_mode", "payment_date"),

        # Most frequent query will be "show me payments WHERE invoice_id = ".."""
        Index("idx_payments_invoiceid", "invoice_id"),
        
        # This serves the GST period aggregation query directly
        Index(
            "idx_payments_tenant_realized", 
            "tenant_id", "is_realized", "payment_date"
        ),
    )

    # Tenancy: Links the payment to a specific business 
    # Ensures "Business A cannot see the bank records or cash collections of Business B "
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), 
        ForeignKey("tenants.id", ondelete="RESTRICT"), 
        nullable=False
    )

    # Points to the Specific bill being paid 
    # Reconciliation - It tells the system which specific debts is being settled by this money
    invoice_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), 
        ForeignKey("invoices.id", ondelete="RESTRICT"), 
        nullable=False
    )

    # Records the day the money was received 
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Uses Numeric(15,2), mapped to python Decimal for guarantee 
    # absolute precision to monetary values and zero rounding errors
    amount: Mapped[Decimal] = mapped_column(Numeric(15,2), nullable=False)

    # stores the Enum as a standard VARCHAR for safer alembic migration. 
    # Defaults to CASH as it requires the least amount of secondary metadata.
    payment_mode: Mapped[PaymentMode]= mapped_column(
        String(30), 
        nullable=False, 
        server_default=text(f"'{PaymentMode.CASH.value}'")
    )

    # Crucial for digital/bank reconciliation (UTR, Cheque Number, UPI Transaction ID).
    # Optional because CASH settlements do not generate reference numbers.
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Marks whether this payment has actually cleared/been received.
    # Post-dated cheques → is_realized = False until clearing date.
    # All GST reports filter WHERE is_realized = True.
    # Set to True by payment_service.py on confirmation of receipt.
    is_realized: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false")
    )

    # Unstructured context layer for accountants to note anomalies 
    # A free text areas for extra context 
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit Trail: Tracks which specific user/employee manually recorded this transaction.
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"), 
        nullable=True
    )

    # Relationships - Inter Relations between models at python level 
    # Payment belongs to Many to One relationship
    # Payment(Many) ----> Tenant(One)
    # Payment(Many) ----> Invoice(One)
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



