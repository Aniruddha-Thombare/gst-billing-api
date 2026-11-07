from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken


async def delete_expired_refresh_tokens_batch(
    db: AsyncSession, *, cutoff: datetime, batch_size: int,
) -> int:
    """
    System-wide maintenance (deliberately not tenant-scoped: expiry is
    tenant-independent). Deletes at most batch_size rows so no single
    statement holds locks for long. Returns the number deleted.
    """
    expired_ids = (
        select(RefreshToken.id)
        .where(RefreshToken.expires_at < cutoff)
        .limit(batch_size)
    )
    result = await db.execute(
        delete(RefreshToken)
        .where(RefreshToken.id.in_(expired_ids))
        .execution_options(synchronize_session=False)
    )
    return result.rowcount