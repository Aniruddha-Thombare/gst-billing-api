from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import idempotency_repository
from app.core.exceptions import (
    DuplicateRequestInProgressError,
    IdempotencyKeyReusedWithDifferentPayloadError,
)

@dataclass
class IdempotencyOutcome:
    is_replay: bool
    cached_response: str | None
    row_id: UUID | None


async def try_reserve(
    db: AsyncSession, *, tenant_id: UUID, endpoint: str, idempotency_key: str, request_hash: str,
) -> IdempotencyOutcome:
    """
    Call ONCE, as the first statement inside the caller's already-open
    `async with db.begin()` — which MUST also wrap the entire business
    operation and the eventual completion write as ONE atomic transaction.

    Because reservation + work + completion always commit together, a
    'processing' row is never visible to another transaction: a genuine
    concurrent replay blocks at the INSERT (Postgres unique-index
    contention) until the original resolves, then sees either a committed
    'completed' row or nothing. There is deliberately no stale-processing
    reclaim here — if a future caller does NOT wrap this in one atomic
    transaction with its real work, it must implement its own reclaim.
    """
    try:
        async with db.begin_nested():
            row = await idempotency_repository.create_processing(
                db, tenant_id=tenant_id, endpoint=endpoint,
                idempotency_key=idempotency_key, request_hash=request_hash,
            )
        return IdempotencyOutcome(is_replay=False, cached_response=None, row_id=row.id)
    except IntegrityError:
        pass  # savepoint rolled back; outer transaction still healthy

    existing = await idempotency_repository.get(
        db, tenant_id=tenant_id, endpoint=endpoint, idempotency_key=idempotency_key,
    )
    if existing is None:
        # Prior blocking transaction rolled back; safe to reserve fresh.
        row = await idempotency_repository.create_processing(
            db, tenant_id=tenant_id, endpoint=endpoint,
            idempotency_key=idempotency_key, request_hash=request_hash,
        )
        return IdempotencyOutcome(is_replay=False, cached_response=None, row_id=row.id)

    if existing.request_hash != request_hash:
        raise IdempotencyKeyReusedWithDifferentPayloadError(idempotency_key)

    if existing.status == "completed":
        return IdempotencyOutcome(is_replay=True, cached_response=existing.response_body, row_id=existing.id)

    # Unreachable under the atomic-transaction invariant above — a real
    # 'processing' row can never be visible here. Fail loudly rather than
    # silently proceed, so a contract violation surfaces immediately
    # instead of causing a duplicate execution.
    raise DuplicateRequestInProgressError(idempotency_key)


async def mark_completed_in_open_txn(
        db: AsyncSession, *,tenant_id: UUID, row_id: UUID, response_json: str
) -> None:
    """
    Store the serialized response on the reservation and flip it to
    'completed'. Must be called inside the same transaction as
    try_reserve and the business work, so all three commit together.
    """
    await idempotency_repository.mark_completed(
        db, tenant_id=tenant_id, row_id=row_id, response_body=response_json
    )
