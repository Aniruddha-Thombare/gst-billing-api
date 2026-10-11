from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.sql import text
from sqlalchemy import String, DateTime, Text, UniqueConstraint, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class IdempotencyKey(BaseModel):
    """
    One row per (tenant, endpoint, client-supplied key). Guarantees one
    logical client operation executes at most once, even when the client
    cannot tell whether its first attempt succeeded.

    request_hash: SHA-256 of the business-relevant request fields (see
    payment_service.compute_request_fingerprint). Reusing a key with a
    DIFFERENT hash is rejected, not silently replayed — protects against a
    buggy/malicious client reusing a key for a genuinely different request.

    INVARIANT: any caller of this table's reservation MUST wrap the
    reservation, the real business work, and the completion write in one
    atomic transaction (see idempotency_service.try_reserve docstring).
    Under that invariant, a 'processing' row is never visible to another
    transaction, so no stale-processing reclaim is needed here — do not
    add one back unless a future caller breaks that invariant.
    """
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        CheckConstraint("status IN ('processing', 'completed')", 
                name="check_idempotency_status",
        ),

        UniqueConstraint(
            "tenant_id", "endpoint", "idempotency_key",
            name="uq_idempotency_tenant_endpoint_key",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
            PG_UUID(as_uuid=True),
            ForeignKey("tenants.id", ondelete="CASCADE"), 
            nullable=False
        )

    endpoint: Mapped[str] = mapped_column(String(100), nullable=False)

    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)

    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="processing",
        server_default=text("'processing'")
    )

    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )