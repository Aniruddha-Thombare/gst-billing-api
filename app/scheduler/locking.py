from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("scheduler.locking")


@asynccontextmanager
async def advisory_lock(engine: AsyncEngine, key: int):
    """
    Yields True if this process won the cluster-wide lock for `key`, else False.
    The lock lives on a dedicated AUTOCOMMIT connection, so there is no open
    transaction for idle_in_transaction_session_timeout to kill.
    """
    conn = await engine.connect()
    acquired = False
    try:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        acquired = bool((await conn.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": key},
        )).scalar_one())
        yield acquired
    finally:
        try:
            if acquired:
                await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
        except Exception:
            # Never return a connection that may still hold the lock to the pool.
            logger.exception("advisory unlock failed; discarding connection")
            await conn.invalidate()
        finally:
            await conn.close()