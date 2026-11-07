from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import reconciliation_repository
from app.repositories.reconciliation_repository import LedgerMismatch

logger = logging.getLogger("scheduler.reconciliation")

MAX_REPORTED_PER_KIND = 200


@dataclass(frozen=True)
class ReconciliationReport:
    mismatches: list[LedgerMismatch]
    truncated: bool

    @property
    def mismatch_count(self) -> int:
        return len(self.mismatches)


def _cap(rows: list[LedgerMismatch]) -> tuple[list[LedgerMismatch], bool]:
    return rows[:MAX_REPORTED_PER_KIND], len(rows) > MAX_REPORTED_PER_KIND


def _log_mismatch(mismatch: LedgerMismatch) -> None:
    logger.error("ledger_mismatch %s", json.dumps({
        "kind": mismatch.kind,
        "tenant_id": str(mismatch.tenant_id),
        "invoice_id": str(mismatch.invoice_id),
        "invoice_number": mismatch.invoice_number,
        "stored": str(mismatch.stored_amount),
        "actual": str(mismatch.actual_amount),
    }))


async def run_ledger_reconciliation(db: AsyncSession) -> ReconciliationReport:
    """
    Read-only. Verifies that each invoice's stored paid / credited / refunded
    totals equal the sum of their source rows. Runs in one REPEATABLE READ
    READ ONLY snapshot so all three checks see the same moment in time.
    Never modifies data: a mismatch is reported for a human to investigate.
    """
    async with db.begin():
        await db.connection(
            execution_options={"isolation_level": "REPEATABLE READ", "postgresql_readonly": True}
        )
        limit = MAX_REPORTED_PER_KIND + 1
        paid = await reconciliation_repository.find_paid_amount_mismatches(db, limit=limit)
        credited = await reconciliation_repository.find_credited_amount_mismatches(db, limit=limit)
        refunded = await reconciliation_repository.find_refunded_amount_mismatches(db, limit=limit)

    mismatches: list[LedgerMismatch] = []
    truncated = False
    for rows in (paid, credited, refunded):
        kept, was_cut = _cap(rows)
        mismatches.extend(kept)
        truncated = truncated or was_cut

    for mismatch in mismatches:
        _log_mismatch(mismatch)

    if mismatches:
        logger.error("Ledger reconciliation FOUND %d mismatches (truncated=%s)", len(mismatches), truncated)
    else:
        logger.info("Ledger reconciliation OK: 0 mismatches")
    return ReconciliationReport(mismatches=mismatches, truncated=truncated)