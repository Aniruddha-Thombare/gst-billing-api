from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select, update, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice
from app.models.invoice_item import InvoiceItem
from app.models.party import Party 


_ZERO = Decimal("0.00")


async def create(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    invoice_number: str,
    invoice_type: str,
    invoice_date: date,
    due_date: date | None,
    financial_year: str,
    party_id: UUID,
    party_gstin: str | None,
    party_state_code: str,
    supply_type: str,
    place_of_supply: str,
    reverse_charge: bool,
    subtotal: Decimal,
    discount_amount: Decimal,
    taxable_amount: Decimal,
    cgst_amount: Decimal,
    sgst_amount: Decimal,
    igst_amount: Decimal,
    cess_amount: Decimal,
    total_amount: Decimal,
    notes: str | None,
    terms: str | None,
    original_invoice_id: UUID | None,
    created_by: UUID,
) -> Invoice:
    """
    Insert a new invoice header row and flush to obtain the generated id.

    Does NOT write outstanding_amount: it is a GENERATED column
    (Invoice total - Cash received - Credit notes + Cash returned). A draft therefore reads
    outstanding_amount == total_amount. AR and aging queries MUST filter
    on invoice_status IN ('sent', 'partial') and never rely on
    outstanding_amount alone, or drafts will be counted as receivables.

    Does NOT commit. The caller (invoice_service._create_invoice_atomic) wraps
    this together with bulk_create_line_items inside one transaction.
    """
    invoice = Invoice(
        tenant_id=tenant_id,
        invoice_number=invoice_number,
        invoice_type=invoice_type,
        invoice_date=invoice_date,
        due_date=due_date,
        financial_year=financial_year,
        party_id=party_id,
        party_gstin=party_gstin,
        party_state_code=party_state_code,
        supply_type=supply_type,
        place_of_supply=place_of_supply,
        reverse_charge=reverse_charge,
        subtotal=subtotal,
        discount_amount=discount_amount,
        taxable_amount=taxable_amount,
        cgst_amount=cgst_amount,
        sgst_amount=sgst_amount,
        igst_amount=igst_amount,
        cess_amount=cess_amount,
        total_amount=total_amount,
        paid_amount=_ZERO,
        invoice_status="draft",
        is_locked=False,
        locked_at=None,
        notes=notes,
        terms=terms,
        original_invoice_id=original_invoice_id,
        created_by=created_by,
        updated_by=created_by,
    )
    db.add(invoice)
    await db.flush()  # materialises invoice.id and DB-generated columns (eager_defaults)
    return invoice


async def bulk_create_line_items(
    db: AsyncSession,
    *,
    line_items: list[InvoiceItem],
) -> None:
    """
    Insert all line items for one invoice in a single flush.

    The caller builds each InvoiceItem in memory (tenant_id, invoice_id and
    all tax fields set) and passes the list here. This function's only job
    is the bulk insert.

    Does NOT commit: part of the caller's transaction.
    """
    db.add_all(line_items)
    await db.flush()


async def get_by_id_with_line_items(
    db: AsyncSession,
    *,
    invoice_id: UUID,
    tenant_id: UUID,
) -> Invoice | None:
    """
    Fetch one invoice with all line items eagerly loaded (selectinload:
    two queries, no row duplication for the 1:N relationship).

    populate_existing=True forces a refresh of any copy of this invoice
    already in the session. The update_* functions below use Core UPDATE
    with synchronize_session=False and the session uses
    expire_on_commit=False, so without this a re-read would return stale
    attributes.
    """
    result = await db.execute(
        select(Invoice)
        .where(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
        .options(selectinload(Invoice.line_items))
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def get_by_id_for_update(
    db: AsyncSession,
    *,
    invoice_id: UUID,
    tenant_id: UUID,
) -> Invoice | None:
    """
    Fetch one invoice with a SELECT ... FOR UPDATE row lock.

    Used by send_invoice, void_invoice, record_payment, cancel_payment,
    credit note creation and credit note application. The lock is held
    until the caller's transaction commits or rolls back; a concurrent
    request for the same invoice blocks here.

    populate_existing=True guarantees the returned attributes are the
    committed values read under the lock, never a stale session copy.
    """
    result = await db.execute(
        select(Invoice)
        .where(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def update_ledger_state(
    db: AsyncSession, *, invoice_id: UUID, tenant_id: UUID, paid_amount: Decimal,
    credited_amount: Decimal, refunded_amount: Decimal, status: str, updated_by: UUID,
) -> None:
    """
    Writes the four ledger inputs and the derived status. outstanding_amount
    and refund_due_amount are GENERATED and recomputed by Postgres.
    Does NOT commit: caller wraps in a transaction.
    """
    await db.execute(
        update(Invoice)
        .where(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
        .values(
            paid_amount=paid_amount, credited_amount=credited_amount,
            refunded_amount=refunded_amount, invoice_status=status,
            updated_by=updated_by, updated_at=datetime.now(timezone.utc),
        )
        .execution_options(synchronize_session=False)
    )


async def update_void_state(
    db: AsyncSession,
    *,
    invoice_id: UUID,
    tenant_id: UUID,
    voided_by: UUID,
    void_reason: str,
) -> None:
    """
    Transitions an invoice to void. Writes invoice_status='void' plus the
    void audit trail (voided_at, voided_by, void_reason).

    Does NOT touch paid_amount or outstanding_amount:
    ledger_rules.validate_invoice_is_voidable already guarantees
    paid_amount == 0 before this is called.

    Does NOT commit: caller wraps in a transaction.
    """
    await db.execute(
        update(Invoice)
        .where(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
        .values(
            invoice_status="void",
            voided_at=datetime.now(timezone.utc),
            voided_by=voided_by,
            void_reason=void_reason,
            updated_by=voided_by,
            updated_at=datetime.now(timezone.utc),
        )
        .execution_options(synchronize_session=False)
    )


async def update_submission_state(
    db: AsyncSession,
    *,
    invoice_id: UUID,
    tenant_id: UUID,
    updated_by: UUID,
) -> None:
    """
    Transition invoice from draft to sent and lock it.

    Does NOT commit: caller wraps in a transaction.
    """
    values = {
        "invoice_status": "sent",
        "is_locked": True,
        "locked_at": datetime.now(timezone.utc),
        "locked_by": updated_by,
        "updated_by": updated_by,
        "updated_at": datetime.now(timezone.utc),
    }

    await db.execute(
        update(Invoice)
        .where(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
        .values(**values)
        .execution_options(synchronize_session=False)
    )


async def get_total_credited(
    db: AsyncSession,
    *,
    original_invoice_id: UUID,
    tenant_id: UUID,
) -> Decimal:
    """
    Sum of total_amount across all SUBMITTED credit notes (status sent,
    partial or paid) referencing this invoice. Drafts and voided credit
    notes are excluded: they were never applied to the ledger.

    Used by credit note creation (cap check) and by cancel_payment
    (recomputing paid_amount as active payments + credits).

    COALESCE guards against SUM() returning NULL when none exist.
    """
    result = await db.execute(
        select(func.coalesce(func.sum(Invoice.total_amount), _ZERO))
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.original_invoice_id == original_invoice_id,
            Invoice.invoice_type == "credit_note",
            Invoice.invoice_status.in_(("sent", "partial", "paid")),
        )
    )
    return result.scalar_one()


async def find_recent_similar_invoice(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    party_id: UUID,
    invoice_type: str,
    amount: Decimal,
    window_minutes: int = 24 * 60,
) -> Invoice | None:
    """
    Most recent non-void, non-cancelled invoice of the same type, for the
    same party and the same stored total, created within the window.
    Backs the soft (overridable) duplicate-invoice check.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    result = await db.execute(
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.party_id == party_id,
            Invoice.invoice_type == invoice_type,
            Invoice.total_amount == amount,
            Invoice.invoice_status.notin_(("void", "cancelled")),
            Invoice.created_at >= cutoff,
        )
        .order_by(Invoice.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_active_credit_note_for_original(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    original_invoice_id: UUID,
    amount: Decimal,
) -> Invoice | None:
    """
    Any non-void, non-cancelled credit note against this original invoice
    with exactly this stored total. Backs the hard (no override) duplicate
    credit note block. Includes drafts on purpose.
    """
    result = await db.execute(
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.original_invoice_id == original_invoice_id,
            Invoice.invoice_type == "credit_note",
            Invoice.total_amount == amount,
            Invoice.invoice_status.notin_(("void", "cancelled")),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_page(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    status: str | None,
    invoice_type: str | None,
    party_id: UUID | None,
    date_from: date | None,
    date_to: date | None,
    after: tuple[date, UUID] | None,
    limit: int,
) -> list[tuple[Invoice, str]]:
    """
    One page of invoices, newest first (invoice_date DESC, id DESC), with the
    party name joined in the same query (no N+1). Keyset pagination: `after`
    is the (invoice_date, id) of the last row of the previous page.
    The caller passes limit = page_size + 1 to detect a next page.
    """
    stmt = (
        select(Invoice, Party.name)
        .join(Party, and_(Party.id == Invoice.party_id, Party.tenant_id == Invoice.tenant_id))
        .where(Invoice.tenant_id == tenant_id)
    )
    if status is not None:
        stmt = stmt.where(Invoice.invoice_status == status)
    if invoice_type is not None:
        stmt = stmt.where(Invoice.invoice_type == invoice_type)
    if party_id is not None:
        stmt = stmt.where(Invoice.party_id == party_id)
    if date_from is not None:
        stmt = stmt.where(Invoice.invoice_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Invoice.invoice_date <= date_to)
    if after is not None:
        stmt = stmt.where(tuple_(Invoice.invoice_date, Invoice.id) < tuple_(after[0], after[1]))

    stmt = stmt.order_by(Invoice.invoice_date.desc(), Invoice.id.desc()).limit(limit)
    result = await db.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]