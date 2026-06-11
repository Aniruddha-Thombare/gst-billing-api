import hashlib
from typing import TYPE_CHECKING
from datetime import datetime, timezone
from uuid import uuid4, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Index, Text, String, DateTime, UniqueConstraint, ForeignKey
from sqlalchemy.sql import text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.user import User

class RefreshToken(BaseModel):
    """
    ORM model for the refresh_tokens table.

    Stores a SHA-256 hash of the issued refresh token — never the raw token.
    If the database is breached, the attacker has 64-character hex strings
    that cannot be reversed to the original JWT. Useless without the raw value.

    Enables logout and forced session revocation, which stateless JWTs alone
    cannot provide. To revoke a session, set revoked_at to the current timestamp.
    The is_valid property then returns False, and the refresh endpoint rejects it.
    """
    __tablename__ = "refresh_tokens"

    __table_args__ = (

        # One hash cannot exist twice (prevents duplicate tokens attacks)
        # Automatice Index - we look up tokens by hash on every refresh updates;
        # without an index this is a full table scan.
        UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),

        # This supports logout all sessions, list active sessions and revoke user sessions
        Index("idx_refresh_tokens_user_active", "user_id", "revoked_at")
    )

    # Every User must belong to a particular tenant 
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Every refresh token must belong to a user 
    # ondelete = "CASCADE". If the user is deleted, their tokens are deleted too
    # this prevents orphaned rows that would leak memory 
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # We NEVER store a raw token, Only its SHA-256(64 hex characters)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Uses timezone-aware UTC to prevent "Timezone" chaos in accounting
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    # We use a timestamp instead of a boolean so we know WHEN it was revoked
    # NULL  → token is still valid
    # set   → token was explicitly revoked (logout / password change)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    # Optional — stores User-Agent string or device label
    # Helps users see "logged in from Chrome on Mac" in a sessions UI later
    device_info: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationship (optional, for ORM Joins)
    # lazy="noload" - do Not auto-load the user when you fetch the refresh token
    user: Mapped["User"] = relationship(
        "User",
        back_populates="refresh_tokens",
        lazy="noload"
    )

    # @staticmethod - It is decorator. 
    # It belongs to the class rather than the instance of the class
    # It overrides the Regular method requirement of self parameter in python 
    @staticmethod
    def hash_token(raw_token: str) -> str:
        """
        Produces the SHA-256 hex digest of a raw token string.

        Called in TWO places:
          1. When storing a new refresh token   → store the hash
          2. When a client sends their token back → hash and compare

        Takes a plain-text refresh token,.encode() - encodes it into a SHA-256 hash.
        .hexdigest() - converts that hash string into 64 characters string (nums and letters)
        """  
        return hashlib.sha256(raw_token.encode()).hexdigest()
    
    # @property - tells sqlalchemy these are not columns instead they are smart variables.
    # Which will calculates the answer at exact millisecond you asked for them  
    @property
    def is_revoked(self) -> bool:
        """
        It checks whether someone manually killed the session or not.
        """
        return self.revoked_at is not None

    @property
    def is_expired(self) -> bool:
        """
        Compares the current timezone with the token expire period 
        It checks if the token has lived past its 7-day lifespan.
        """
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def is_valid(self) -> bool:
        """
        A token is only usable if it is neither expired nor revoked
        """
        return not self.is_revoked and not self.is_expired
