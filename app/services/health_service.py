"""Health service — liveness and readiness decisions. No SQL here."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import health_repository

logger = logging.getLogger(__name__)

_DB_TIMEOUT_SECONDS = 3.0


async def check_readiness(db: AsyncSession) -> dict[str, str]:
    """
    Ready = the database answers within 3 seconds.
    Returns per-dependency status; 'ok' means every check passed.
    """
    checks: dict[str, str] = {}
    try:
        await asyncio.wait_for(health_repository.ping_database(db), timeout=_DB_TIMEOUT_SECONDS)
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 - any failure means "not ready"; details go to the log, not the client
        logger.exception("Readiness check failed: database")
        checks["database"] = "unavailable"
    return checks
