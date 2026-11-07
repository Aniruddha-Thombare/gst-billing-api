from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.core.error_reporting import init_error_reporting
from app.core.logging_config import configure_logging
from app.scheduler import jobs
from app.scheduler.database import engine

logger = logging.getLogger("scheduler")

_ONE_HOUR = 3600


def build_scheduler() -> AsyncIOScheduler:
    """All times are UTC. 21:30 UTC = 03:00 IST, 22:00 UTC = 03:30 IST."""
    scheduler = AsyncIOScheduler(timezone="UTC")
    common = dict(max_instances=1, coalesce=True, misfire_grace_time=_ONE_HOUR, replace_existing=True)
    scheduler.add_job(
        jobs.purge_refresh_tokens_job, CronTrigger(hour=21, minute=30),
        id="purge_refresh_tokens", **common,
    )
    scheduler.add_job(
        jobs.ledger_reconciliation_job, CronTrigger(hour=22, minute=0),
        id="ledger_reconciliation", **common,
    )
    return scheduler


async def _serve() -> None:
    scheduler = build_scheduler()
    scheduler.start()
    for job in scheduler.get_jobs():
        logger.info("scheduled job=%s next_run=%s", job.id, job.next_run_time)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    logger.info("shutting down")
    scheduler.shutdown(wait=False)
    await engine.dispose()


async def _run_once(name: str) -> int:
    try:
        if name == "cleanup":
            await jobs.purge_refresh_tokens_job()
            return 0
        mismatches = await jobs.ledger_reconciliation_job()
        return 1 if mismatches else 0
    finally:
        await engine.dispose()


def main() -> None:
    configure_logging(settings.LOG_LEVEL)
    init_error_reporting()
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-once", choices=["cleanup", "reconcile"])
    args = parser.parse_args()

    if args.run_once:
        sys.exit(asyncio.run(_run_once(args.run_once)))
    asyncio.run(_serve())


if __name__ == "__main__":
    main()