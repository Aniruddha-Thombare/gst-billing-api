from __future__ import annotations
from uuid import UUID
from sqlalchemy.sql import text 
from typing import List, TYPE_CHECKING
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy import CheckConstraint, Text, Boolean, String,ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import BaseModel
from app.models.enum import PartyType
from app.models.constants import GSTIN_REGEX, STATE_CODE_REGEX, PIN_CODE_REGEX, PAN_REGEX

# Importing models for python level mapping
if TYPE_CHECKING:
    from app.models.tenant import Tenant
    from app.models.invoice import Invoice


class Party(BaseModel):
    """
    A Container for all counterparties (customers or vendors) scoped strictly to one tenant.
    - It stores their legal identities and tax profiles so that when an invoice is generated,
      the system knows exactly which GST rules to apply and which name to print on the document.
    - It exists to ensure Data Consistency and Tax compliance. Instead of manually typing a 
      customer's GSTIN or StateCode on every single invoice - which leads to human error - we just 
      record it once here. This ensures every transaction with that party is mapped directly and 
      correctly for GST filing. 
    """

    __tablename__ = "parties"

    # This tells SQLAlchemy: "For this entire table, fetch all DB defaults on save"
    __mapper_args__ = {"eager_defaults": True}

    __table_args__ = (

        # FORMAT CONSTRAINTS: 
        # 1. These fire on INSERT and UPDATE only — zero SELECT overhead.
        # 2. Rejects structurally invalid tax identifiers 
        # before they reach the GST portal and cause return filing failures.
        CheckConstraint(
            f"gstin IS NULL OR gstin ~ '{GSTIN_REGEX}'", 
            name="check_party_gstin_format"
        ),

        CheckConstraint(
            f"pan IS NULL OR pan ~ '{PAN_REGEX}'", 
            name="check_party_pan_format"
        ),

        CheckConstraint(
            f"state_code ~ '{STATE_CODE_REGEX}'", 
            name="check_state_code_format"
        ),

        CheckConstraint(
            f"party_type IN ({', '.join(repr(e.value) for e in PartyType)})", 
            name="check_party_type"
        ),

        # Has to be of 6 digits and the first digit should be non zero 
        # This constraint ensure that mandatory check. 
        CheckConstraint(f"pincode ~ '{PIN_CODE_REGEX}'", name= "check_pincode_format"),

        # Party does not store pan - so cross validation needs a different approach.
        CheckConstraint(
            "gstin IS NULL OR pan IS NULL OR SUBSTRING(gstin, 3, 10) = pan",
            name="check_party_gstin_pan_consistency"
        ),

        # Telling the database that the combination of (tenant_id and gstin) must be unique
        # It ensures no duplicate GSTINs for one tenant
        # This enforces uniqueness only where GSTIN exists, and correctly ignores NULL rows.
        Index(
            "uq_party_tenant_gstin", 
            "tenant_id", "gstin",
            unique=True,
            postgresql_where = text("gstin IS NOT NULL")
        ),

        # You will frequently run this query - 
        # WHERE tenant_id = ".." AND is_active = True 
        # The DB will skip any old inactive vendors or customers
        # only return the ones you are currently doing business with
        Index("idx_party_tenant_active", "tenant_id", "is_active"),

        # When the user clicks on "View Customers"
        # the API runs WHERE tenant_id = ".." AND party_type = "customer"
        Index("idx_party_tenant_type", "tenant_id", "party_type"),
    )

    # Mandatory for Multi-Tenancy - Every row is strictly scoped to one tenant
    # RESTRICT - Prevents accidental tenant deletion while parties exist
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), 
        ForeignKey("tenants.id", ondelete="RESTRICT"),  
        nullable=False
    )

    # Business Identity - business name displayed on invoices 
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # GST and Pan Identity - GSTIN is unique per tenant, NOT globally. 
    # Two tenants can both have the same vendor registered 
    # this is normal in multi-tenant SaaS.
    # Is Nullable: B2C customers / composition dealers have no GSTIN
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)

    pan: Mapped[str | None] = mapped_column(String(10), nullable=True)
    
    # Address - Mandatory for adding Place of Party on Tax invoice
    address_line1: Mapped[str] = mapped_column(Text, nullable=False)

    address_line2: Mapped[str | None] = mapped_column(Text, nullable=True)

    city: Mapped[str] = mapped_column(String(100), nullable=False)

    pincode: Mapped[str] = mapped_column(String(6), nullable=False)
    
    # CRITICAL: drives all GST calculation
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)

    # Contact INFO
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # PartyType - To see the said business is a Customer or Vendor. 
    # It uses PartyType enums to dictate whether it is a customer or vendor 
    party_type: Mapped[PartyType] = mapped_column(
        String(20), 
        nullable=False, 
        server_default=text(f"'{PartyType.CUSTOMER.value}'")
    )

    # System_Flag - Only look for active customers and vendors 
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        server_default=text("true")
    )
 
    # Relationships - Inter relations between the tables at python level 
    # Party belongs to Many to one relationship with Tenant
    # Party (Many Parties) ----> One(Tenant) 
    tenant: Mapped["Tenant"] = relationship(
        "Tenant", 
        back_populates="parties", 
        lazy="noload"
    )

    # Party belongs to One to Many relationship with Invoices
    # Party (Many Parties) ----> One(Invoice) 
    invoices: Mapped[List["Invoice"]] = relationship(
        "Invoice", 
        back_populates="party", 
        lazy="noload"
    )
