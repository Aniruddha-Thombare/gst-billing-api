from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idempotency_key import IdempotencyKey


async def get(
    db: AsyncSession, *, tenant_id: UUID, endpoint: str, idempotency_key: str,
) -> IdempotencyKey | None:
    """
    Fetch an idempotency row by its natural key (tenant_id, endpoint,
    idempotency_key). Returns None if this key has never been used.
    """
    result = await db.execute(
        select(IdempotencyKey).where(
            IdempotencyKey.tenant_id == tenant_id,
            IdempotencyKey.endpoint == endpoint,
            IdempotencyKey.idempotency_key == idempotency_key,
        )
    )
    return result.scalar_one_or_none()


async def create_processing(
    db: AsyncSession, *, tenant_id: UUID, endpoint: str, idempotency_key: str, request_hash: str,
) -> IdempotencyKey:
    """
    Insert a reservation row with status='processing' and flush.

    Raises IntegrityError on the (tenant_id, endpoint, idempotency_key)
    unique constraint if the key already exists. The caller wraps this in
    a SAVEPOINT (begin_nested) and handles the collision.

    Does NOT commit: part of the caller's transaction.
    """
    row = IdempotencyKey(
        tenant_id=tenant_id, endpoint=endpoint, idempotency_key=idempotency_key,
        request_hash=request_hash, status="processing",
    )
    db.add(row)
    await db.flush()
    return row


async def mark_completed(
    db: AsyncSession, *, tenant_id: UUID, row_id: UUID, response_body: str,
) -> None:
    """
    Flip a reservation to status='completed' and store the serialized
    response for future replays. Scoped by tenant_id and row id.

    Does NOT commit: part of the caller's transaction, so the reservation,
    the business work and the completion commit or roll back together.
    """
    await db.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.id == row_id, IdempotencyKey.tenant_id == tenant_id)
        .values(status="completed", response_body=response_body, completed_at=func.now())
        .execution_options(synchronize_session=False)
    )