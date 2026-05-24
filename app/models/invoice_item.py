from __future__ import annotations
from uuid import UUID
from decimal import Decimal
from typing import TYPE_CHECKING
from sqlalchemy.sql import text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy import Computed, ForeignKey, CheckConstraint, Index,Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import BaseModel
from app.models.constants import HSN_SAC_CODE_REGEX

# Importing models for python level mapping
if TYPE_CHECKING:
    from app.models.invoice import Invoice


class InvoiceItem(BaseModel):
    """
    Represents an Individual line entry for a product or service within an invoice.

    This model stroes the transactional data required for legal billing and GST Compliance.
    It handles item-specific pricing, quantity, and multi-tier tax calculations
    (CGST, SGST, IGST and CESS)

    Data integrity is enforce through strict numeric precision and database-level 
    check constraints to ensure financial accuracy. 
    """

    __tablename__ = "invoice_items"
    
    # This tells SQLAlchemy: "For this entire table, fetch all DB defaults on save"
    __mapper_args__ = {"eager_defaults": True}

    __table_args__ = (

        # Ensures taxable amount never exceeds the total amount.
        CheckConstraint("total_amount >= taxable_amount", 
            name="check_invoice_item_tax_not_exceed_total"
        ),
        # Every transaction must involve at least a fractional quantity. 
        CheckConstraint("quantity > 0", 
            name="check_invoice_item_quantity_positive"
        ),
        # prevents zero or negative pricing, ensuring every line has a valid value.
        CheckConstraint("rate > 0", name="check_invoice_item_rate_positive"),

        # Ensuring Line ordering (1,2,3...) is logical and positive
        CheckConstraint("line_number > 0", 
            name="check_invoice_item_line_number_positive"
        ),

        # Ensures no negative taxable amount can be stored 
        CheckConstraint("taxable_amount >= 0", 
            name="check_invoice_item_taxable_value_positive"
        ),
        
        # Ensuring it meets the code digits requirements for HSN, SAC. 
        CheckConstraint(
            f"hsn_sac_code IS NULL OR hsn_sac_code ~ '{HSN_SAC_CODE_REGEX}'",
            name="check_invoice_item_hsn_sac_format"
        ),
        # GST Compliance - Validates that the entered GST rate matches 
        # officially recognised Indian tax slabs
        CheckConstraint(
            "gst_rate IN (0, 0.125, 0.25, 0.75, 1.5, 2.5, 3, 5, 6, 9, 12, 14, 18, 28)", 
            name="check_invoice_item_gst_rate_valid"
        ),

        # Discount percentage should be in range of (1 - 100)
        CheckConstraint(
            "discount_percent >= 0 AND discount_percent <= 100",
            name="check_invoice_item_discount_percent_range"
        ),

        # Ensuring the CGST and SGST applies to Intra state supply 
        # Ensuring the IGST applies to Interstate supply 
        CheckConstraint(
            "(igst_amount = 0 AND igst_rate = 0)"
            " OR "
            "(cgst_amount = 0 AND sgst_amount = 0 AND cgst_rate = 0 AND sgst_rate = 0)",
            name="check_invoice_item_gst_mutual_exclusivity"
        ),

        # Speed up the retrieval process for the user while generating full invoice.
        # Faster in Scoping to the specific business for multi tenancy. 
        Index("idx_invoice_item_tenant_invoice", "tenant_id", "invoice_id"),
    )

    # Relationship - Current Line Invoice item is related to which invoice_id
    # CASCADE: If the parent invoice is deleted, these items are useless

    invoice_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"), 
        nullable= False 
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"), 
        nullable=False
    )

    # line ordering within the invoice (1,2,3 ....)
    line_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # Description: Product/Service description 
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Primary Identification - hsn_sac_code: 
    # HSN for goods(4-8 digits), SAC for services(6 digits)
    hsn_sac_code: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # unit: pcs - pieces; kg; ltr; hrs; etc. - free text, not an enum 
    unit: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'PCS'")
    )

    # Higher precision (12, 3) allows for fractional units like kilograms (e.g., 1.550 kg).
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)

    # High precision (15, 4) handles sub-paisa rates common in bulk wholesale.
    rate: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)

    # Records Discount related rates and actual discount provided.
    discount_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),  nullable=False, default=Decimal("0"),
        server_default=text("0")
    )

    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0"),
        server_default=text("0")
    )

    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)

    # GST RATES AND AMOUNTS — both stored, never recomputed
    # gst_rate: full rate (18%)
    # cgst_rate = sgst_rate = gst_rate / 2 for intrastate
    # igst_rate = gst_rate for interstate
    # Exactly one of (cgst+sgst) OR igst will be non-zero per line item.
    
    gst_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),  nullable=False, default=Decimal("0"),
        server_default=text("0")
    )

    cgst_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),  nullable=False, default=Decimal("0"),
        server_default=text("0")
    )

    cgst_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0"),
        server_default=text("0")
    )

    sgst_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),  nullable=False, default=Decimal("0"),
        server_default=text("0")
    )

    sgst_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0"),
        server_default=text("0")
    )

    igst_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),  nullable=False, default=Decimal("0"),
        server_default=text("0")
    )

    igst_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0"),
        server_default=text("0")
    )

    cess_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),  nullable=False, default=Decimal("0"),
        server_default=text("0")
    )

    cess_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0"),
        server_default=text("0")
    )

    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), 
        Computed(
            "taxable_amount + cgst_amount + sgst_amount + igst_amount + cess_amount",
            persisted=True
        )    
    )

    # Relationships - Inter relations between the tables at python level.
    # Invoice_item belongs to Many to One relationship with the invoice.
    invoice: Mapped["Invoice"] = relationship(
        "Invoice", 
        back_populates="line_items", 
        lazy="noload"
    )