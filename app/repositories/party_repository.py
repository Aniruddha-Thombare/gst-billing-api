from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update, tuple_, func 
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.party import Party


async def create(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    name: str,
    gstin: str | None,
    pan: str | None,
    address_line1: str,
    address_line2: str | None,
    city: str,
    pincode: str,
    state_code: str,
    email: str | None,
    phone: str | None,
    party_type: str,
    created_by: UUID,
) -> Party:
    """
    Insert one party and flush to obtain id and DB defaults.
    May raise IntegrityError on uq_party_tenant_gstin; the service maps it.
    Does NOT commit: caller wraps in a transaction.
    """
    party = Party(
        tenant_id=tenant_id,
        name=name,
        gstin=gstin,
        pan=pan,
        address_line1=address_line1,
        address_line2=address_line2,
        city=city,
        pincode=pincode,
        state_code=state_code,
        email=email,
        phone=phone,
        party_type=party_type,
        is_active=True,
        created_by=created_by,
        updated_by=created_by,
    )
    db.add(party)
    await db.flush()
    return party


async def get_by_id(
    db: AsyncSession, *, party_id: UUID, tenant_id: UUID,
) -> Party | None:
    """
    Fetch a party by id, scoped to a tenant. A party belonging to another
    tenant returns None, indistinguishable from a missing one.

    populate_existing=True so a read after update_fields / set_active
    (Core UPDATE, session has expire_on_commit=False) never returns a
    stale in-session copy.

    Type and is_active checks are business rules, done by the service layer.
    """
    result = await db.execute(
        select(Party)
        .where(Party.tenant_id == tenant_id, Party.id == party_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def update_fields(
    db: AsyncSession,
    *,
    party_id: UUID,
    tenant_id: UUID,
    updated_by: UUID,
    values: dict[str, object],
) -> int:
    """
    Overwrite the given editable columns. Returns rows affected (0 = no such
    party for this tenant). May raise IntegrityError on uq_party_tenant_gstin.
    Does NOT commit: caller wraps in a transaction.
    """
    result = await db.execute(
        update(Party)
        .where(Party.id == party_id, Party.tenant_id == tenant_id)
        .values(**values, updated_by=updated_by, updated_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    )
    return result.rowcount


async def set_active(
    db: AsyncSession,
    *,
    party_id: UUID,
    tenant_id: UUID,
    is_active: bool,
    updated_by: UUID,
) -> int:
    """
    Set is_active. Returns rows affected (0 = no such party for this tenant).
    Setting the value it already has is a no-op success, so retries converge.
    Does NOT commit: caller wraps in a transaction.
    """
    result = await db.execute(
        update(Party)
        .where(Party.id == party_id, Party.tenant_id == tenant_id)
        .values(is_active=is_active, updated_by=updated_by, updated_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    )
    return result.rowcount


async def list_page(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    party_type: str | None,
    is_active: bool | None,
    name_prefix: str | None,
    after: tuple[str, UUID] | None,
    limit: int,
) -> list[Party]:
    """
    One page of parties, alphabetical (name ASC, id ASC). Keyset pagination;
    the caller passes limit = page_size + 1. name_prefix is a
    case-insensitive "starts with" match; LIKE wildcards in it are escaped.
    """
    stmt = select(Party).where(Party.tenant_id == tenant_id)
    if party_type is not None:
        stmt = stmt.where(Party.party_type == party_type)
    if is_active is not None:
        stmt = stmt.where(Party.is_active == is_active)
    if name_prefix:
        escaped = (
            name_prefix.lower()
            .replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        stmt = stmt.where(func.lower(Party.name).like(escaped + "%", escape="\\"))
    if after is not None:
        stmt = stmt.where(tuple_(Party.name, Party.id) > tuple_(after[0], after[1]))

    stmt = stmt.order_by(Party.name.asc(), Party.id.asc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())