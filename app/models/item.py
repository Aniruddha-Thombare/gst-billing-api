from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class Item(BaseModel):
    """Per-tenant product/service catalog. Pre-fills invoice lines in the UI;
    invoices keep their own frozen copy of every value."""

    __tablename__ = "items"

    __table_args__ = (
        CheckConstraint("rate >= 0", name="check_items_rate_non_negative"),

        CheckConstraint("gst_rate >= 0 AND gst_rate <= 100", name="check_items_gst_rate_range"),

        CheckConstraint("cess_rate >= 0 AND cess_rate <= 100", name="check_items_cess_rate_range"),

        Index("uq_items_tenant_name_lower", "tenant_id", text("lower(name)"), unique=True),

        Index("idx_items_tenant_name_id", "tenant_id", "name", "id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), 
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    hsn_sac_code: Mapped[str | None] = mapped_column(String(8), nullable=True)

    unit: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'PCS'")
    )

    rate: Mapped[Decimal] = mapped_column(Numeric(17, 2), nullable=False)

    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    cess_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0")
    )

    is_service: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), 
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), 
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )