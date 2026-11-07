from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.scheduler.database import SessionFactory, engine
from app.scheduler.locking import advisory_lock
from app.services import maintenance_service, reconciliation_service

logger = logging.getLogger("scheduler.jobs")

LOCK_REFRESH_TOKEN_CLEANUP = 7_301_001
LOCK_LEDGER_RECONCILIATION = 7_301_002


async def _run_locked(
    job_name: str, lock_key: int, work: Callable[[AsyncSession], Awaitable[int]],
) -> int | None:
    """Runs `work` only if no other scheduler instance is running this job."""
    async with advisory_lock(engine, lock_key) as acquired:
        if not acquired:
            logger.info("job=%s skipped: another instance holds the lock", job_name)
            return None
        logger.info("job=%s started", job_name)
        async with SessionFactory() as db:
            result = await work(db)
        logger.info("job=%s finished result=%s", job_name, result)
        return result


async def purge_refresh_tokens_job() -> int | None:
    return await _run_locked(
        "purge_refresh_tokens", LOCK_REFRESH_TOKEN_CLEANUP,
        maintenance_service.purge_expired_refresh_tokens,
    )


async def ledger_reconciliation_job() -> int | None:
    async def work(db: AsyncSession) -> int:
        report = await reconciliation_service.run_ledger_reconciliation(db)
        return report.mismatch_count

    return await _run_locked("ledger_reconciliation", LOCK_LEDGER_RECONCILIATION, work)