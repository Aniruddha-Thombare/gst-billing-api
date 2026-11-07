from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_by_id(
    db: AsyncSession, *, tenant_id: UUID, user_id: UUID, for_update: bool = False,
) -> User | None:
    stmt = select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_for_tenant(db: AsyncSession, *, tenant_id: UUID) -> list[User]:
    """A tenant has a handful of staff, so this list is deliberately unpaginated."""
    stmt = select(User).where(User.tenant_id == tenant_id).order_by(User.full_name, User.id)
    return list((await db.execute(stmt)).scalars().all())


async def set_role(db: AsyncSession, *, user: User, role) -> None:
    user.role = role
    await db.flush()


async def set_active(db: AsyncSession, *, user: User, is_active: bool) -> None:
    user.is_active = is_active
    await db.flush()


async def set_password_hash(db: AsyncSession, *, user: User, hashed_password: str) -> None:
    user.hashed_password = hashed_password
    await db.flush()