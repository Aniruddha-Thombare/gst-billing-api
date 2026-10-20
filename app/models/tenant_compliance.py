from datetime import date 
from uuid import UUID 
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy.sql import text
from sqlalchemy import (
    ForeignKey, CheckConstraint, String, Numeric, Boolean, 
    Date, Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.constants import FINANCIAL_YEAR_REGEX
from app.models.base import BaseModel

# Importing models for python level mapping
if TYPE_CHECKING:
    from app.models.tenant import Tenant

class TenantCompliance(BaseModel):
    """
    Accepting and recording tenant compliance information for invoice generation. 

    - Annual turnover will be used to determine the HSN_SAC code digits. 
    - Composition turnover is only provided if a particular business belongs to 
    composition scheme in country like India. 
    - is_msme is to determine the tenant belongs to which category of business 
    based on that the calculations will be done. 

    """
    
    __tablename__ = "tenant_compliances"
    
    # This tells SQLAlchemy: "For this entire table, fetch all DB defaults on save"
    __mapper_args__ = {"eager_defaults": True}

    __table_args__ = (

        # Ensures that the financial year format is as per the Indian financial 
        # systems including GST portals, tax filings and accounting software 
        CheckConstraint(
            f"financial_year ~ '{FINANCIAL_YEAR_REGEX}' ",
            name="check_tenant_compliant_financial_year"
        ), 

        # annual turnover and composition turnover can never be negative 
        CheckConstraint("annual_turnover >= 0", name="check_tenant_annual_turnover_positive"),

        CheckConstraint(
            "composition_turnover >= 0", 
            name="check_tenant_composition_turnover_positive"
        ),

        # Effective date validation - Ensuring effective_to should be future to effective_from 
        # This prevents any invalid periods. 
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="check_effective_dates"
        ),

        # Financial year and tenant id must be unique 
        UniqueConstraint("tenant_id", "financial_year", name="uq_tenant_financial_year"),

        # Composite Index - We will use this in almost every query 
        # tenant filter - to get the financial year for particular tenant 
        Index(
            "idx_tenant_compliance_financial_year",
            "tenant_id", "financial_year"
        )
        
    )

    # To determine this compliance info belongs to which tenant
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False
    )

    financial_year: Mapped[str] = mapped_column(String(7), nullable=False)

    # To record the annual turnover of the tenant for previous financial year
    # Default - Zero. Because the tenant who started his business in current financial 
    # year may don't have any previous years turnover 
    annual_turnover: Mapped[Decimal] = mapped_column(
        Numeric(17,2), nullable=False, default=Decimal("0"),
        server_default=text("0")
    )

    composition_turnover: Mapped[Decimal] = mapped_column(
        Numeric(17,2), nullable=False, default=Decimal("0"),
        server_default=text("0")
    )

    # MSME - Micro, Small and Medium Enterprises. To ensures the statutory limits 
    # are applied to the particular business 
    # Micro - Investment limit(up to Rs. 1 crore), Annual turnover limit(up to Rs. 5 crore)
    # Small - Investment limit(up to Rs. 10 crore), Annual turnover limit(up to Rs. 50 crore)
    # Medium - Investment limit(up to Rs. 50 crore), Annual turnover limit(up to Rs. 250 crore)
    is_msme: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        server_default=text("false")
    )

    effective_from: Mapped[date] = mapped_column(Date, nullable=False)

    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Relationships - Inter Relations between the tables at a Python level
    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        back_populates="compliance_profiles",
        lazy="noload"
    )
