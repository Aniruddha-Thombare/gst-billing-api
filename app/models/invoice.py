from __future__ import annotations
from uuid import UUID
from decimal import Decimal 
from typing import List, TYPE_CHECKING
from datetime import datetime, date
from sqlalchemy import (
    CheckConstraint, UniqueConstraint, Index, ForeignKey, 
    String, Computed, Date, Text, Numeric, Boolean, DateTime)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.sql import text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import BaseModel
from app.models.enum import InvoiceStatus, InvoiceType, SupplyType
from app.models.constants import FINANCIAL_YEAR_REGEX

# Importing models for python level mapping
if TYPE_CHECKING:
    from app.models.tenant import Tenant
    from app.models.invoice_item import InvoiceItem
    from app.models.payment import Payment
    from app.models.party import Party

# DOMAIN ENUMS
# All inherit (str, Enum) — stored as String in DB, never as PG ENUM type.
# Adding new values only requires updating CheckConstraint + migration.


class Invoice(BaseModel):
    """
    Primary financial document for sales, purchases, credit notes, debit notes.\
    
    It performs three Critical roles:
    1. Legal Snapshot: Captures 'frozen' party data (GSTN/ State) to preserve
        historical accuracy even if master record change. 
    2. Tax Compliance: Automatically determines supply classification 
        (Interstate VS Intrastate) to drive GST Calculation 
    3. Financial Integrity: Enforces strict business rules at the schema level
        to prevent inconsistent accounting records or negative financial values.

    """
    
    __tablename__ = "invoices"
    
    # This tells SQLAlchemy: "For this entire table, fetch all DB defaults on save"
    __mapper_args__ = {"eager_defaults": True}

    __table_args__ = (
        # Enum constraints - Database level validation
        # Ensures Database rejects any value which is not explicitly defined in the Enum class
        CheckConstraint(
            f"supply_type IN ({', '.join(repr(e.value) for e in SupplyType)})",
            name="check_invoice_supply_type"
        ),
        CheckConstraint(
            f"invoice_status IN ({', '.join(repr(e.value) for e in InvoiceStatus)})",
            name="check_invoice_status"
        ),
        CheckConstraint(
            f"invoice_type IN ({', '.join(repr(e.value) for e in InvoiceType)})",
            name="check_invoice_type"
        ),

        # BUSINESS RULE CONSTRAINT
        # credit_note and debit_note MUST refer to an original invoice.
        # sales and purchase must NOT refer to one.  
        CheckConstraint(
            f" (invoice_type IN ({', '.join(repr(e.value) for e in [InvoiceType.CREDIT_NOTE, InvoiceType.DEBIT_NOTE])})"
            f" AND original_invoice_id IS NOT NULL)"
            f" OR "
            f" (invoice_type IN ({', '.join(repr(e.value) for e in [InvoiceType.SALES, InvoiceType.PURCHASE])})"
            f" AND original_invoice_id IS NULL)",
            name="check_invoice_original_ref_consistency"
        ),

        # Enforces the Standardized "YYYY-YY" format (eg: 2025-26)
        # required for Indian GST Filling. 
        CheckConstraint(
            f"financial_year ~ '{FINANCIAL_YEAR_REGEX}'", 
            name="check_invoice_financial_year_format"
        ),

        # A bill due before it was raised is logically impossible and will corrupt the data.
        # Ensuring the due date is after the invoice was raised 
        CheckConstraint(
            "due_date IS NULL OR due_date >= invoice_date",
            name="check_invoice_due_date_after_invoice_date"
        ),
        # FINANCIAL INTEGRITY CONSTRAINTS
        # Prevent negative or logically inconsistent stored amounts.
        CheckConstraint("subtotal >= 0", name="check_invoice_subtotal_positive"),

        CheckConstraint(
            "taxable_amount >= 0", 
            name="check_invoice_taxable_positive"
        ),

        CheckConstraint("total_amount >= 0", name="check_invoice_total_positive"),

        CheckConstraint("paid_amount >= 0", name="check_invoice_paid_positive"),

        CheckConstraint(
            "paid_amount <= total_amount", 
            name="check_invoice_paid_not_exceed_total"
        ),

        # Ensuring CGST and SGST applies to intrastate and IGST column becomes zero 
        # Ensuring IGST applies to Interstate and CGST and SGST column becomes zero
        CheckConstraint(
            f" (supply_type = '{SupplyType.INTRASTATE.value}' AND igst_amount = 0)"
            f"  OR "
            f" (supply_type = '{SupplyType.INTERSTATE.value}' AND cgst_amount = 0 AND sgst_amount = 0)"
            f"  OR "
            f" (supply_type IN ({', '.join(repr(e.value) for e in [SupplyType.EXPORT, SupplyType.SEZ])}) "
            f"  AND cgst_amount = 0 AND sgst_amount = 0)",
            name="check_invoice_gst_mutual_exclusivity"
        ),

        # Preventing allowing of any negative values for these columns 
        CheckConstraint("discount_amount >= 0", name="check_invoice_discount_non_negative"),
        CheckConstraint("cgst_amount >= 0", name="check_invoice_cgst_non_negative"),
        CheckConstraint("sgst_amount >= 0", name="check_invoice_sgst_non_negative"),
        CheckConstraint("igst_amount >= 0", name="check_invoice_igst_non_negative"),
        CheckConstraint("cess_amount >= 0", name="check_invoice_cess_non_negative"),
        CheckConstraint("outstanding_amount >= 0", name="check_invoice_outstanding_non_negative"),

        CheckConstraint("credited_amount >= 0 AND credited_amount <= total_amount",
                name="check_invoice_credited_not_exceed_total"),
                
        CheckConstraint("refunded_amount >= 0 AND refunded_amount <= paid_amount",
                name="check_invoice_refunded_valid"),
        # Invoice number is unique within a business
        # businesses to use the same numbering sequence(eg: two tenants having INV -001)
        UniqueConstraint(
            "tenant_id", 
            "invoice_number", 
            name="uq_invoice_tenant_number"
        ),

        # Invoices sorted by date and type for a tenant
        Index(
            "idx_invoices_tenant_date_type", 
            "tenant_id", 
            "invoice_date", 
            "invoice_type"
        ),

        # Status filter: to get outstanding, draft or overdue invoice lists 
        Index("idx_invoices_tenant_status",  "tenant_id", "invoice_status"),

        # Keyset list: ORDER BY invoice_date DESC, id DESC within a tenant
        Index("idx_invoices_tenant_date_id", "tenant_id", "invoice_date", "id"),

        # Replaces idx_invoices_tenant_party. Serves party ledgers AND the
        # duplicate-invoice check (party_id + created_at >= cutoff).
        Index("idx_invoices_tenant_party_created", "tenant_id", "party_id", "created_at"),

        # Credit note lookups: get_total_credited and
        # get_active_credit_note_for_original. Partial, since most invoices
        # have no original and shouldn't bloat the index.
        Index(
            "idx_invoices_tenant_original",
            "tenant_id", "original_invoice_id",
            postgresql_where=text("original_invoice_id IS NOT NULL"),
        ),

        # Invoice type + financial year: GSTR -1/ GSTR 3B scoped to a financial year 
        Index(
            "idx_invoices_tenant_type_fy", 
            "tenant_id", 
            "invoice_type", 
            "financial_year"
        ),

        # AR aging: open receivables only. Partial, so it stays small however
        # many paid/draft/void invoices exist.
        Index(
            "idx_invoices_open_receivables",
            "tenant_id", "party_id", "due_date",
            postgresql_where=text(
                "invoice_status IN ('sent', 'partial') AND invoice_type IN ('sales', 'debit_note')"
            ),
        ),

        # Refund-due lookups (money owed to customers)
        Index(
            "idx_invoices_refund_due",
            "tenant_id",
            postgresql_where=text("refund_due_amount > 0"),
        ),
        
    )

    # Tenancy - To determine the Counterparty belongs to which business(Tenant)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"), 
        nullable=False
    )

    # Invoice Details
    # invoice_number: generated by sequence_service - format PREFIX/FY/NNNN
    invoice_number: Mapped[str] = mapped_column(String(50), nullable=False)

    # Ensuring the Database should accept only enum values
    invoice_type: Mapped[InvoiceType] = mapped_column(
        String(20), 
        nullable=False, 
        server_default=text(f"'{InvoiceType.SALES.value}'")
    )

    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)

    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    financial_year: Mapped[str] = mapped_column(String(7), nullable=False)

    # PARTY REFERENCE + SNAPSHOT
    # party_id: live FK — for joins, reports, party ledger
    # party_gstin, party_state_code: FROZEN at creation time
    #   Do not join party table to get these — use snapshot fields.
    
    party_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("parties.id", ondelete="RESTRICT"), 
        nullable=False
    )

    party_gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)

    party_state_code: Mapped[str] = mapped_column(String(2),  nullable=False)
 
    # GST SUPPLY CLASSIFICATION
    # supply_type: determined by comparing tenant.state_code vs party_state_code
    # place_of_supply: 2-digit state code; "97" for exports
    # reverse_charge: RCM applies when purchasing from unregistered dealers
    supply_type: Mapped[SupplyType] = mapped_column(
        String(15), 
        nullable=False, 
        server_default=text(f"'{SupplyType.INTRASTATE.value}'")
    )

    place_of_supply:  Mapped[str] = mapped_column(String(2),  nullable=False)

    reverse_charge: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        server_default=text("false")
    )

    # FINANCIAL AMOUNTS — all Numeric(15,2), never float
    # Stored at invoice level as SUM of line item amounts.
    # Never recompute from line items after creation — use stored values.

    subtotal: Mapped[Decimal] = mapped_column(Numeric(17, 2), nullable=False)

    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(17, 2), nullable=False, default=Decimal("0"),
        server_default=text("0")
    )

    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(17, 2), nullable=False)

    cgst_amount: Mapped[Decimal] = mapped_column(
        Numeric(17, 2), nullable=False, default=Decimal("0"),
        server_default=text("0")
    )

    sgst_amount: Mapped[Decimal] = mapped_column(
        Numeric(17, 2), nullable=False, default=Decimal("0"),
        server_default=text("0")
    )

    igst_amount: Mapped[Decimal] = mapped_column(
        Numeric(17, 2), nullable=False, default=Decimal("0"),
        server_default=text("0")
    )
    cess_amount: Mapped[Decimal] = mapped_column(
        Numeric(17, 2), nullable=False, default=Decimal("0"),
        server_default=text("0")
    )

    total_amount: Mapped[Decimal] = mapped_column(Numeric(17, 2), nullable=False)
    
    # cash received (active payments only)
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(17,2), nullable=False, default=Decimal("0"),
        server_default=text("0")
    )

    # sum of sent credit notes against this invoice
    credited_amount: Mapped[Decimal] = mapped_column(
        Numeric(17, 2), nullable=False, default=Decimal("0"), server_default=text("0")
    )  

    # sum of active refunds paid out
    refunded_amount: Mapped[Decimal] = mapped_column(
        Numeric(17, 2), nullable=False, default=Decimal("0"), server_default=text("0")
    )  

    outstanding_amount: Mapped[Decimal] = mapped_column(
        Numeric(17, 2),
        Computed(
            "CASE WHEN invoice_type = 'credit_note' THEN 0 "
            "ELSE GREATEST(total_amount - credited_amount - paid_amount + refunded_amount, 0) END",
            persisted=True,
        ),
    )

    refund_due_amount: Mapped[Decimal] = mapped_column(
        Numeric(17, 2),
        Computed(
            "CASE WHEN invoice_type = 'credit_note' THEN 0 "
            "ELSE GREATEST(paid_amount + credited_amount - refunded_amount - total_amount, 0) END",
            persisted=True,
        ),
    )
    
    # Status 
    # invoice_status: full invoice lifecycle
    # payment_status: payment-specific state — separate from invoice status
    invoice_status: Mapped[InvoiceStatus] = mapped_column(
        String(20), 
        nullable=False, 
        server_default=text(f"'{InvoiceStatus.DRAFT.value}'")
    )

    # NOTES AND TERMS — operational, not used in tax logic
    # notes - This is a free-text area where a business can leave a custom message for the client on that specific invoice.
    # terms - In India, almost every B2B GST invoice has a "Terms and Conditions" section. This legally protects the seller.
    notes: Mapped[str | None] = mapped_column(Text, nullable=True) 

    terms: Mapped[str | None] = mapped_column(Text, nullable=True) 

    # CREDIT_NOTE / DEBIT_NOTE REFERENCE
    # Self-referential FK — only populated for credit_note and debit_note types.
    # CheckConstraint above enforces that sales/purchase leave this NULL.

    original_invoice_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="RESTRICT"), 
        nullable=True
    )

    # IMMUTABILITY LOCK
    # is_locked: "Set to True when the invoice is submitted (send_invoice). 
    #    Immutable from then on."
    # Service layer MUST check this before any mutation and raise 409.
    # locked_at and locked_by: audit trail for the lock action.
    # Dependency: users.id — user.py must be migrated before invoices.
    
    is_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        server_default=text("false")
    )

    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), 
        nullable=True
    )

    locked_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"), 
        nullable=True
    )

    # AUDIT FIELDS
    # created_by, updated_by: who performed the action
    # Dependency: users.id — user.py must be migrated before invoices.

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"), 
        nullable=True
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"), 
        nullable=True
    )

    # VOID AUDIT TRAIL
    # Set when an invoice is voided (issued in error, before any payment
    # was received — see ledger_rules for the exact voidable-state rule).
    # Mirrors the cancellation audit pattern on Payment: never delete,
    # record who/when/why. voided_at doubles as the "is this voided"
    # check alongside invoice_status == "void" — both are set together,
    # atomically, in the same UPDATE.
    voided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    voided_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )

    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships - Inter Relations between the tables at a Python level 
    # Invoice belongs to One to One relationships with (tenant,party,  Invoice(self reference))
    # Invoice belongs to One to Many relationships with (InvoiceLineItem, Payment)
    tenant: Mapped["Tenant"] = relationship(
        "Tenant", 
        back_populates="invoices", 
        lazy="noload", 
        foreign_keys="Invoice.tenant_id"
    )

    party: Mapped["Party"] = relationship(
        "Party", 
        back_populates="invoices", 
        lazy="noload"
    )

    line_items: Mapped[List["InvoiceItem"]] = relationship(
        "InvoiceItem", 
        back_populates="invoice", 
        lazy="noload"
    )

    payments: Mapped[List["Payment"]] = relationship(
        "Payment", 
        back_populates="invoice", 
        lazy="noload"
    )

    original_invoice: Mapped["Invoice | None"] = relationship(
        "Invoice", 
        remote_side="Invoice.id", 
        foreign_keys="Invoice.original_invoice_id", 
        lazy="noload"
    )
