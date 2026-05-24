from __future__ import annotations
from uuid import UUID, uuid4
from datetime import datetime, timezone
from sqlalchemy import DateTime
from sqlalchemy.sql import text 
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped,mapped_column
from app.database import Base

# creating reusable abstract model

class BaseModel(Base):
    """
    Abstract base inherited by every ORM Model.
    Provides:
    - id : UUID primary key (PostgreSQL native UUID type, not String)
    - created_at: set once on INSERT, never changes — audit trail
    - updated_at: auto-updated on every UPDATE — change detection
    - deleted_at: set on soft-delete; NULL means record is active

    """
    # Tells SQLAlchemy NOT to create a table named "BaseModel"
    __abstract__ = True

    # PRIMARY ID: Uses native PostgreSQL UUID for massive scalability.
    # Double-Locked: Python generates it via uuid4; 
    # DB generates it via gen_random_uuid() if Python fails.
    id : Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
        nullable=False,
    )

    # CREATED_AT: It tells when the record was created 
    # Uses timezone-aware UTC to prevent "Timezone" chaos in accounting
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("NOW()"),
        default=lambda: datetime.now(timezone.utc),
        nullable = False
    )
    
    # UPDATED_AT: It tells when the record was updated. 
    # The 'onupdate' trigger ensures this timestamp refreshes every time you save a change
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("NOW()"),
        default=lambda: datetime.now(timezone.utc),
        onupdate= lambda: datetime.now(timezone.utc),
        nullable = False
    )

    # DELETED_AT: The safety Net (soft delete). 
    # Instead of permanently deleting financial data (which is dangerous) we just stamp it here.
    # if this Null, the record is active. If it has a date, it is "archived".
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

class AuditBase(Base):
    """
    Abstract Base for models that use composite PKs.
    Provides audit timestamps without auto-generated id column.

    Use for: InvoiceSequence, and any future junction/composite-key tables
    """
    __abstract__ = True

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("NOW()"),
        default = lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("NOW()"),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None
    )


    
