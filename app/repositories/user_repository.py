from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User     # your existing User ORM model
from app.models.enum import UserRole


async def get_by_email(db: AsyncSession, *, email: str) -> User | None:
    """
    Fetch a user by email address.
    
    Email is GLOBALLY unique across the entire platform (see
    User.uq_user_email — a plain UniqueConstraint on email alone, not
    scoped to tenant_id). One email belongs to exactly one user, in
    exactly one tenant, ever. This is why login can look a user up by
    email alone, with no tenant_id filter — there is structurally never
    more than one match.

    """
    result = await db.execute(
        select(User).where(User.email == email.lower())
        # .lower() → normalize email before query
        # Ensures "User@Example.com" finds the same row as "user@example.com"
    )
    return result.scalars().first()


async def get_by_id(db: AsyncSession, *, user_id: UUID, tenant_id: UUID) -> User | None:
    """
    Fetch a user by their ID, scoped to a tenant.
    
    ALWAYS include tenant_id in lookups by ID.
    This prevents a tenant_A user from accessing tenant_B user data
    even if they somehow obtain the UUID.
    This is the tenant isolation rule.
    """
    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.tenant_id == tenant_id,    # MANDATORY — tenant isolation
        )
    )
    return result.scalar_one_or_none()


async def create(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    email: str,
    hashed_password: str,
    full_name: str,
    role: UserRole,
) -> User:
    """
    Insert a new User row.
    
    Accepts hashed_password (not plain password).
    Password hashing happens in auth_service.py before this is called.
    Repositories never receive or handle plain text passwords.
    
    Does NOT commit — service layer controls the transaction.
    """
    user = User(
        tenant_id=tenant_id,
        email=email.lower(),            # normalize to lowercase on store
        hashed_password=hashed_password,
        full_name=full_name,
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()    # get user.id without committing
    return user


async def update_last_login(db: AsyncSession, *, user_id: UUID, tenant_id: UUID) -> None:
    """
    Update the last_login_at timestamp.
    Called after every successful login.
    
    Uses UPDATE ... WHERE instead of fetching the full User object
    just to update one field. More efficient at scale.
    
    synchronize_session=False → tells SQLAlchemy not to try to update
    any in-memory User objects. We do not need the updated object back.
    """
    await db.execute(
        update(User)
        .where(User.id == user_id, User.tenant_id == tenant_id)
        .values(last_login_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    )