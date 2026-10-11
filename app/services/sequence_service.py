from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sequence import InvoiceSequence


# Default prefixes applied when a tenant has not configured a custom one.
#   INV/2024-25/0001  (sales)
#   PUR/2024-25/0001  (purchase)
#   CN/2024-25/0001   (credit note)
#   DN/2024-25/0001   (debit note)
#   PAY/2024-25/0001  (payment receipt)
_DEFAULT_PREFIXES: dict[str, str] = {
    "sales": "INV",
    "purchase": "PUR",
    "credit_note": "CN",
    "debit_note": "DN",
    "payment": "PAY",
}

# Zero-padded width for the sequence number: INV/2024-25/0001 (4 digits)
_SEQUENCE_PADDING = 4


async def get_next_invoice_number(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    financial_year: str,
    invoice_type: str,
    custom_prefix: str | None = None,
) -> str:
    """
    Atomically increment and return the next number for a
    (tenant_id, financial_year, invoice_type) combination.

    Opens NO transaction of its own: it runs inside the caller's open
    transaction (or savepoint), so the increment commits or rolls back
    together with the document that uses the number. No gaps, no reuse.

    CONCURRENCY, existing row: SELECT ... FOR UPDATE locks it. A second
    concurrent request for the same combination blocks here until the
    first transaction finishes, then reads the already-incremented
    last_number. No two transactions ever see the same value.

    CONCURRENCY, first number ever (no row yet): two requests may both
    find no row and both INSERT; the second raises IntegrityError on
    constraint invoice_sequences_pkey. The CALLER handles it:
    invoice_service._create_invoice_atomic retries once inside a SAVEPOINT,
    and payment_service._retry_or_raise retries the whole transaction once.

    RETURN FORMAT: "PREFIX/YYYY-YY/NNNN", e.g. "INV/2024-25/0001".
    """
    result = await db.execute(
        select(InvoiceSequence)
        .where(
            InvoiceSequence.tenant_id == tenant_id,
            InvoiceSequence.financial_year == financial_year,
            InvoiceSequence.invoice_type == invoice_type,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    sequence_row = result.scalar_one_or_none()

    if sequence_row is None:
        # First number for this combination: seed the row.
        prefix = custom_prefix or _DEFAULT_PREFIXES.get(invoice_type, "INV")
        sequence_row = InvoiceSequence(
            tenant_id=tenant_id,
            financial_year=financial_year,
            invoice_type=invoice_type,
            prefix=prefix,
            last_number=1,
        )
        db.add(sequence_row)
    else:
        sequence_row.last_number += 1

    # Flush so the increment (or the seed INSERT, which is where a race
    # surfaces as IntegrityError) happens now, inside the caller's
    # transaction, before the number is used.
    await db.flush()

    prefix = custom_prefix or sequence_row.prefix or _DEFAULT_PREFIXES.get(invoice_type, "INV")
    return f"{prefix}/{financial_year}/{sequence_row.last_number:0{_SEQUENCE_PADDING}d}"