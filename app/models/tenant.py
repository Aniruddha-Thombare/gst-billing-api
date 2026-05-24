from __future__ import annotations
from typing import List, TYPE_CHECKING
from sqlalchemy.sql import text 
from datetime import datetime
from sqlalchemy import (String, Boolean, Text, 
        DateTime, CheckConstraint, UniqueConstraint, Index)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import BaseModel
from app.models.enum import RegistrationType
from app.models.constants import GSTIN_REGEX, PAN_REGEX, PIN_CODE_REGEX, STATE_CODE_REGEX

# Importing models for python level mapping
if TYPE_CHECKING:
    from app.models.user import User 
    from app.models.invoice import Invoice
    from app.models.sequence import InvoiceSequence
    from app.models.payment import Payment
    from app.models.party import Party


class Tenant(BaseModel):
    """
    A GST Registered Business using our Saas platform 
    - It stores the identity and tax profile of a business. It acts as a 
      "container" - everything else in the application (invoices, users, 
       payments) must be linked to a specific Tenant so the data stays separated. 
    - This supports Multi-Tenancy. It allows to host hundreds of different 
      companies (Tenants) simultaneously. Without this, Business A can see all the 
      details of business B. This Table acts as a wall between them. 
    """

    __tablename__ = "tenants"
    
    # This tells SQLAlchemy: "For this entire table, fetch all DB defaults on save"
    __mapper_args__ = {"eager_defaults": True}

    __table_args__ = (

        # FORMAT CONSTRAINTS: 
        # 1. These fire on INSERT and UPDATE only — zero SELECT overhead.
        # 2. Rejects structurally invalid tax identifiers 
        # before they reach the GST portal and cause return filing failures.

        CheckConstraint(f"gstin ~ '{GSTIN_REGEX}'", name="check_tenant_gstin_format"),

        CheckConstraint(f"pan ~ '{PAN_REGEX}'", name="check_tenant_pan_format"),
        
        # Mandatory of 2 digits as per Indian GST laws for tax calculations 
        CheckConstraint(f"state_code ~ '{STATE_CODE_REGEX}'", name="check_state_code_format"),

        # Has to be of 6 digits and the first digit should be non zero 
        # This constraint ensure that mandatory check. 
        CheckConstraint(f"pincode ~ '{PIN_CODE_REGEX}'", name= "check_pincode_format"),

        # To enforce PAN - GSTIN alignment. 
        # The characters 3 - 12 in the GST number should match exactly the tenant pan number
        CheckConstraint("SUBSTRING(gstin, 3, 10) = pan", name="check_gstin_pan_consistency"),

        # Ensuring the DB must accept only string values that are stated in enum classes
        CheckConstraint(
            f"registration_type IN ({', '.join(repr(e.value) for e in RegistrationType)})",
            name= "check_registration_type"
        ),
    
        # Verification of business on GST Portal and Search requirement for a client.
        # GSTIN number and Pan number column should not contain any duplicates throughout. 
        # pan + gstin columns are indexed via UniqueConstraint
        UniqueConstraint("gstin", name="uq_tenant_gstin"),

        UniqueConstraint("pan",   name="uq_tenant_pan"),

        # Authentication requirement - As every time user will login in with email
        # No two tenants can shared same email ID
        # email column is indexed via UniqueConstraint
        UniqueConstraint("email", name="uq_tenant_email"), 

        # In almost every query you will include WHERE is_active = True 
        Index("idx_tenant_is_active", "is_active"),

        # When generating GSTR reports. Eg: "Show me all composition dealers"
        # This index makes the grouping and filtering process lightning Fast.
        Index("idx_tenant_registration_type", "registration_type"), 

        # You will query this column - Admin dashboards, compliance reports,reactivation flows.
        # you will run - WHERE deactivated_at IS NOT NULL 
        # WHERE deactivated_at >= '2024-01-01'
        Index("idx_tenant_deactivated_at", "deactivated_at"),
    )

    # Business Identity - Its corporate name
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Exact GST registered name 
    legal_name: Mapped[str] = mapped_column(String(255), nullable= False)  

    # Name of a business use to market and operate itself. 
    trade_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # GST and Tax Identity Number - Social Security Numbers of the app
    gstin: Mapped[str] = mapped_column(String(15), nullable=False) # Always exactly 15 characters

    pan: Mapped[str] = mapped_column(String(10), nullable=False)  # Always exactly 10 characters 

    # Address - Mandatory for adding Place of Business on Tax invoice
    address_line1: Mapped[str] = mapped_column(Text, nullable=False)

    address_line2: Mapped[str | None] = mapped_column(Text, nullable=True)

    city: Mapped[str] = mapped_column(String(100), nullable=False)

    pincode: Mapped[str] = mapped_column(String(6), nullable=False)

    # CRITICAL: drives all GST calculation - same state = CGST + SGST, different = IGST
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)

    # Contact Info
    email: Mapped[str] = mapped_column(String(255), nullable=False)

    phone: Mapped[str | None ] = mapped_column(String(20), nullable=True) 

    # Registration Type - 
    # To see the said business belongs to which type of registration 
    # "regular" | "composition" | "unregistered"
    registration_type: Mapped[RegistrationType] = mapped_column(
        String(20), 
        nullable=False, 
        server_default=text(f"'{RegistrationType.REGULAR.value}'")
    )
    
    # Status - Default = True, stating the business is still using our platform 
    # Unless we manually change the status to False - Tenant account is deactivated
    # It blocks a business from logging in without deleting it records
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
        server_default= text("true")
    )

    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None
    )

    # Relationships - Inter relations between the tables at python level 
    # Tenant belongs to One to Many relationship - 
    # Tenant (One) ----> Many (Users, Parties, Sequences, Invoices, payments)
    users: Mapped[List["User"]] = relationship(
        "User", 
        back_populates="tenant", 
        lazy="noload"
    )

    invoices: Mapped[List["Invoice"]] = relationship(
        "Invoice", 
        back_populates="tenant", 
        lazy="noload", 
        foreign_keys="Invoice.tenant_id"
    )

    parties: Mapped[List["Party"]] = relationship(
        "Party", 
        back_populates="tenant", 
        lazy="noload"
    )

    sequences : Mapped[List["InvoiceSequence"]] = relationship(
        "InvoiceSequence", 
        back_populates="tenant", 
        lazy="noload"
    )

    payments : Mapped[List["Payment"]] = relationship(
        "Payment", 
        back_populates="tenant", 
        lazy="noload"
    )
    

