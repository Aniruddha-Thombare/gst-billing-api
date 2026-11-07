from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item


async def create(db: AsyncSession, *, tenant_id: UUID, created_by: UUID, **values) -> Item:
    item = Item(tenant_id=tenant_id, created_by=created_by, **values)
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


async def get_by_id(
    db: AsyncSession, *, item_id: UUID, tenant_id: UUID, for_update: bool = False,
) -> Item | None:
    stmt = select(Item).where(
        Item.id == item_id, Item.tenant_id == tenant_id, Item.deleted_at.is_(None),
    )
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def apply_values(db: AsyncSession, *, item: Item, values: dict, updated_by: UUID) -> None:
    for key, value in values.items():
        setattr(item, key, value)
    item.updated_by = updated_by
    item.updated_at = datetime.now(timezone.utc)
    await db.flush()


async def set_active(db: AsyncSession, *, item: Item, is_active: bool, updated_by: UUID) -> None:
    item.is_active = is_active
    item.updated_by = updated_by
    item.updated_at = datetime.now(timezone.utc)
    await db.flush()


async def list_page(
    db: AsyncSession, *, tenant_id: UUID, is_active: bool | None,
    name_prefix: str | None, after, limit: int,
) -> list[Item]:
    stmt = select(Item).where(Item.tenant_id == tenant_id, Item.deleted_at.is_(None))
    if is_active is not None:
        stmt = stmt.where(Item.is_active == is_active)
    if name_prefix:
        stmt = stmt.where(Item.name.istartswith(name_prefix, autoescape=True))
    if after is not None:
        after_name, after_id = after
        stmt = stmt.where(tuple_(Item.name, Item.id) > tuple_(after_name, after_id))
    stmt = stmt.order_by(Item.name, Item.id).limit(limit)
    return list((await db.execute(stmt)).scalars().all())