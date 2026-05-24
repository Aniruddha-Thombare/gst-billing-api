from __future__ import annotations
from uuid import UUID 
from sqlalchemy.sql import text
from typing import TYPE_CHECKING
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy import CheckConstraint, ForeignKey, String, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import AuditBase
from app.models.enum import InvoiceType
from app.models.constants import FINANCIAL_YEAR_REGEX, PREFIX_REGEX

# Importing models for python level Mapping
if TYPE_CHECKING:
    from app.models.tenant import Tenant


class InvoiceSequence(AuditBase):
    """
    Atomic Invoice sequence generation for financial documents. 
    - It keeps a live count of the "Last Number" used by a specific business for a 
      specific type of document(like a Sales Invoice) in a specific financial year.
    - Uses a Composite Primary Key to scope sequences per-tenant, 
      per-financial-year, per-type invoice counter.
    """

    __tablename__ = "invoice_sequences"

    # This tells SQLAlchemy: "For this entire table, fetch all DB defaults on save"
    __mapper_args__ = {"eager_defaults": True}

    __table_args__ = (

        # Enum constraints - Database level validation
        # Ensures Database rejects any value which is not explicitly defined in the Enum class
        CheckConstraint(
            f"invoice_type IN ({', '.join(repr(e.value) for e in InvoiceType)})",
            name="check_sequence_invoice_type"
        ),
        
        # Enforces the Standardized "YYYY-YY" format (eg: 2025-26)
        # required for Indian GST Filling.
        CheckConstraint(
            f"financial_year ~ '{FINANCIAL_YEAR_REGEX}'", 
            name="check_sequence_financial_year_format"
        ),

        # Enforces alphanumeric + hyphen format for invoice number prefix.
        # Eg: INV, PO - 2025
        CheckConstraint(
            f"prefix IS NULL OR prefix ~ '{PREFIX_REGEX}'",
            name="check_sequence_prefix_format"
        ),

        # To avoid any accidental negative last_number entries
        CheckConstraint(
            "last_number >= 0", 
            name="check_sequence_last_number_non_negative"),
    )

    # ---- COMPOSITE PRIMARY KEY ----
    # These three columns together uniquely identify one sequence.
    # PostgreSQL automatically creates a B-tree index on all three — no separate index declaration needed.
    # FOR UPDATE in sequence_service locks exactly this row.
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False
    )

    invoice_type: Mapped[InvoiceType] = mapped_column(
        String(20), 
        primary_key=True, 
        nullable=False, 
    )

    financial_year: Mapped[str] = mapped_column(
        String(7), 
        primary_key=True, 
        nullable=False
    )

    # ---- Sequence Data ----
    # PREFIX — tenant-configurable invoice number prefix
    # Example: "INV" → "INV/2024-25/0042"
    # NULL means use the system default for that invoice_type.
    prefix: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # COUNTER — incremented atomically under FOR UPDATE lock
    # Starts at 0. First invoice = 0 + 1 = 1 → formatted as "0001"
    # Never reset mid-year. Resets only when a new financial_year row
    # is inserted (which starts at last_number=0 again).
    last_number: Mapped[int] = mapped_column(
        Integer, nullable=False, 
        default=0, 
        server_default=text("0")
    )

    # Relationships - Inter Relations between models at python level 
    # Sequence belongs to Many to One relationship with Tenant
    tenant: Mapped["Tenant"] = relationship(
        "Tenant", 
        back_populates="sequences", 
        lazy="noload"
    )