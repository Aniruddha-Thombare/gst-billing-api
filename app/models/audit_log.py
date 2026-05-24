from __future__ import annotations
from uuid import UUID
from datetime import datetime 
from sqlalchemy.sql import text
from sqlalchemy.dialects.postgresql import JSONB, INET, UUID as PG_UUID
from sqlalchemy import CheckConstraint, BigInteger, Index, Text, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base 
from app.models.enum import AuditAction, EntityType


class AuditLog(Base):
    """
    Immutable append-only record of every mutation to financial data.

    It tracks the "Who, What, When and Where" of every action - such as creating an invoice,
    updating a payment, or a user logging in. It captures the exact state of a record before 
    and after a change using JSON snapshots, ensuring you have a forensic trail of all activity.

    Design invariants:
    - Does NOT inherit BaseModel. Reason: It has No foreign key references from any other Table
      Therefore, primary key is BIGSERIAL (sequential integer), not UUID. 
    - APPEND-ONLY. No row is ever UPDATE or DELETE.
      updated_at and deleted_at are absent by design — they would be
      meaningless on an immutable log.
    - This table is a compliance requirement, not a feature.
      GST authorities can request audit trails during investigations.
      Records must be retained for the same 6-year period as invoices.
    """

    __tablename__ = "audit_logs"

    # This tells SQLAlchemy: "For this entire table, fetch all DB defaults on save"
    __mapper_args__ = {"eager_defaults": True}

    __table_args__ = (
        
        # Action Validation: Ensuring that only specific, recognized system events like
        # (Create, login, delete) are recorded, keeping the audit trail clean and predictable
        CheckConstraint(
          f"action IN ({', '.join(repr(e.value) for e in AuditAction)})", 
          name="check_audit_logs_audit_action"
        ),

        # Restricts logging to valid tables to ensure the forensic record matches our database schema.
        CheckConstraint(
          f"entity_type IN ({', '.join(repr(e.value) for e in EntityType)})", 
          name="check_audit_logs_entity_type"
        ),

        # Optimized for finding the history of a specific object. 
        # eg: "show me all changes to Invoice #123 over the last year"
        Index("idx_audit_logs_entity_id_type_created", "entity_type","entity_id","created_at"),

        # Essential for tenant specific compliance reports or security reviews.
        Index("idx_audit_logs_tenant_created", "tenant_id", "created_at"),

        # Used for monitoring individual staff activity and "Employee productivity logs"
        Index("idx_audit_logs_user_created", "user_id", "created_at"), 

        # GIN - Generalized Inverted Index, it works on content insided a JSON column
        # This is for Postgresql Level, it lets look inside the JSON and query specific fields
        Index(
            "idx_audit_logs_new_values_gin",
            "new_values",
            postgresql_using="gin"
        ),
        Index(
            "idx_audit_logs_old_values_gin",
            "old_values",
            postgresql_using="gin"
        ),
    )

    # PRIMARY KEY — BIGSERIAL
    # Sequential inserts are critical at 5B+ rows — UUID random insertion causes B-tree fragmentation and slow writes. 
    # Range: 1 to 9,223,372,036,854,775,807 — effectively unlimited.
    id: Mapped[int] = mapped_column(
      BigInteger, primary_key=True, 
      autoincrement=True, nullable=False
    )

    # No Foreign Keys(Loose References)
    # This is done intentionally so that even if a tenant is ever hard deleted (compliance edge case), their audit logs must remain
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    # Actor - who performs this action 
    # if a user is deleted we still need to know thier id - as in who modified this invoice.
    # Nullable= True : system-generated events(eg: auto-lock after GSTR filling) have no associated user
    user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    # Entity Identification - what was changed 
    # entity_type: checkconstraint enforces for allowed values at DB level 
    # entity_id: UUID of the change record

    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)

    entity_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    # Action - What was done 
    # CheckConstraint enforces for allowed values at DB level 

    action: Mapped[AuditAction] = mapped_column(
      String(20), 
      nullable=False, 
    )

    # STATE SNAPSHOTS — JSONB
    # old_values: complete state before the change (NULL for CREATE)
    # new_values: complete state after the change (NULL for DELETE)
    
    # Example for invoice status change:
    # old_values = {"status": "draft", "updated_by": "user-uuid"}
    # new_values = {"status": "sent",  "updated_by": "user-uuid"}
    
    # Store only changed fields, not entire object — keeps rows compact.
    
    old_values: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    new_values: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Request Metadata - for security Investigations
    # ip_address uses PostgreSQL INET type — stores both IPv4 and IPv6 natively with proper indexing support.
    # user_agent: Identifies the device/browser (eg: chrom on windows)

    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)

    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamp - when did this event occur
    # server_default=text("NOW()"): PostgreSQL sets this on INSERT, not Python.
    # No updated_at — this row is never updated after insert.
    created_at: Mapped[datetime] = mapped_column(
      DateTime(timezone=True), 
      server_default=text("NOW()"), 
      nullable=False
    ) 