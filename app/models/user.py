from __future__ import annotations
from uuid import UUID
from typing import TYPE_CHECKING
from datetime import datetime
from sqlalchemy.dialects.postgresql import UUID as PG_UUID 
from sqlalchemy import Integer, String, Boolean, CheckConstraint, UniqueConstraint, Index, DateTime, ForeignKey
from sqlalchemy.sql import text 
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import BaseModel
from app.models.enum import UserRole

# Importing models for python level mapping
if TYPE_CHECKING:
    from app.models.tenant import Tenant 


class User(BaseModel):
    """
    An Authenticated person operating within a tenant's account.
    - It manages Identity and Access Management(IAM). It stores who a person is, 
      their secure credentials, their authorization level(Role), and most importantly
      which business(Tenant) they are allowed to operate within.
    - It ensures that the authenticated person can log in and their actions are 
      restricted to their specific company they belong to. It turns any generic 
      visitor into a specific, authorized operator. 
    """

    __tablename__ = "users"

    # This tells SQLAlchemy: "For this entire table, fetch all DB defaults on save"
    __mapper_args__ = {"eager_defaults": True}

    __table_args__ = (
        
        # Data based level Validation - 
        # Ensuring the role column only accepts valid UserRole enum values. 
        CheckConstraint(
            f"role IN ({', '.join(repr(e.value) for e in UserRole)})",
            name= "check_user_role"
        ),
        # Count of Failed login attempts should be non negative
        CheckConstraint(
            "failed_login_attempts >= 0",
            name="check_failed_login_attempts_non_negative"
        ),

        # Multi-tenancy - Every single query will start with WHERE tenant_id = " "
        # Every login attempt from user will ask for tenant_id and email. 
        UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),

        # In almost every query you will include WHERE is_active = True 
        Index("idx_user_tenant_active", "tenant_id", "is_active"),

        # This index allows the system to quickly group or filter Users 
        # Based on their access level without complete table scan. 
        Index("idx_user_tenant_role", "tenant_id", "role"),

        # You will always query the user last logins or to see active sessions.
        # "Show all users who haven't logged in for 90 days"
        # "Show all active sessions today"
        Index("idx_user_tenant_last_login", "tenant_id", "last_login_at"),

        # auth service will run this check on every login attempt.
        Index("idx_user_locked_until", "tenant_id", "locked_until"),
    )

    # Tenancy - To determine the User belongs to which Tenant 
    # CASCADE: deleting a tenant removes all their user accounts.
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), 
        ForeignKey("tenants.id", ondelete="CASCADE"), 
        nullable=False
    )

    # IDENTITY - email must be unique within tenant
    email: Mapped[str] = mapped_column(String(255), nullable=False)

    # Name of the User who is login in 
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Authentication
    # auth_service.py is the only place that calls bcrypt.hash()
    # This column will never receives a plain text value under any condition.
    hashed_password: Mapped[str] = mapped_column(String(60), nullable=False)

    # Authorization - Enforced at DB schema level 
    # The Permission Badge - it uses UserRole Enum to dictate if a user is an 
    # Owner(full control) or a Viewer(read -only) - which is vital for internal controls
    role: Mapped[UserRole] = mapped_column(
        String(20), 
        nullable=False, 
        server_default=text(f"'{UserRole.ACCOUNTANT.value}'")
    )

    # Status - It allows a manager to block the access of an ex -employee
    # Instantly without deleting their history 
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        server_default=text("true")
    )

    # Session Tracking - the security trail 
    # Updated on every successful login by auth_service.py 
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Incremented on every failed login attempt by auth_service.py
    # Reset to 0 on successful login 
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False, default=0,
        server_default=text("0")
    )

    # Set by auth_service.py after N consecutive failures
    # auth_service checks this Before verifying password
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True, default=None
    )

    # Relationships - Inter relations between the tables at python level 
    # User belongs to Many to one relationship - 
    # User(Many users) ----> One(Tenant) 
    tenant: Mapped["Tenant"] = relationship(
        "Tenant", 
        back_populates="users", 
        lazy="noload"
    )
