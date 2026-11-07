from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import maintenance_repository

logger = logging.getLogger("scheduler.maintenance")

BATCH_SIZE = 5000
MAX_BATCHES = 200  # hard stop: at most 1,000,000 rows per run
RETENTION_AFTER_EXPIRY = timedelta(days=1)


async def purge_expired_refresh_tokens(
    db: AsyncSession, *, now: datetime | None = None,
    batch_size: int = BATCH_SIZE, max_batches: int = MAX_BATCHES,
) -> int:
    """
    Deletes refresh tokens that expired more than a day ago, one short
    transaction per batch. Returns the total deleted.
    """
    cutoff = (now or datetime.now(timezone.utc)) - RETENTION_AFTER_EXPIRY
    total_deleted = 0

    for _ in range(max_batches):
        async with db.begin():
            deleted = await maintenance_repository.delete_expired_refresh_tokens_batch(
                db, cutoff=cutoff, batch_size=batch_size,
            )
        total_deleted += deleted
        if deleted < batch_size:
            break

    logger.info("purged %d expired refresh tokens", total_deleted)
    return total_deleted