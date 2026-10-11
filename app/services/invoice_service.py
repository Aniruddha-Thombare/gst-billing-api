import hashlib, json 

from uuid import UUID
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Final 


from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from app.core.exceptions import (
    InvoiceArithmeticError, InvoiceLockedError, InvoiceNotFoundError,
    InvalidGSTRateError, InvalidHSNCodeError, InvalidInvoiceNumberError,
    OriginalInvoiceNotFoundError, CreditNoteExceedsInvoiceError, 
    InvoiceNotVoidableError, PartyTypeMismatchError, CreditNotePartyMismatchError,
    PossibleDuplicateInvoiceError, DuplicateCreditNoteError, InvoiceNotCreditableError,
    PartyInactiveError, PartyNotFoundError, TenantNotFoundError, InvalidListQueryError 
)

from app.core.pagination import Page, encode_cursor, decode_date_cursor
from app.domain import business_rules, tax_engine, ledger_rules
from app.schemas.invoice import InvoiceCreateRequest, InvoiceResponse, InvoiceSummaryResponse
from app.models.invoice import Invoice
from app.services import idempotency_service
from app.models.invoice_item import InvoiceItem
from app.schemas.invoice import LineItemCreate
from app.services import sequence_service
from app.repositories import ( 
    tenant_repository, party_repository, invoice_repository,
    tenant_compliance_repository ) 


# Module level constant, avoid loading it at every function call    
ONE_HUNDRED: Final[Decimal] = Decimal("100")

TWOPLACES: Final[Decimal] = Decimal("0.01")

ZERO: Final[Decimal] = Decimal("0.00")

def compute_invoice_request_fingerprint(*, tenant_id: UUID, request: InvoiceCreateRequest) -> str:
    payload = {
        "tenant_id": str(tenant_id), "invoice_type": request.invoice_type,
        "party_id": str(request.party_id), "invoice_date": request.invoice_date.isoformat(),
        "original_invoice_id": str(request.original_invoice_id) if request.original_invoice_id else None,
        "declared_grand_total": str(request.declared_grand_total),
        "is_service": request.is_service,
        "due_date": request.due_date.isoformat() if request.due_date else None,
        "line_items": [
            {"description": li.description, "quantity": str(li.quantity), "rate": str(li.rate),
             "gst_rate": str(li.gst_rate), "discount_percent": str(li.discount_percent),
             "hsn_sac_code": li.hsn_sac_code, "cess_rate": str(li.cess_rate)}
            for li in request.line_items
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def _to_money(value: Decimal) -> Decimal:
    """Single rounding point so stored values equal computed values."""
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


async def create_invoice(
    db: AsyncSession, *, tenant_id: UUID, user_id: UUID,
    request: InvoiceCreateRequest, idempotency_key: str,
) -> InvoiceResponse:
    """Owns the ONE outer transaction: reservation + full body + completion."""
    request_hash = compute_invoice_request_fingerprint(tenant_id=tenant_id, request=request)
    async with db.begin():
        outcome = await idempotency_service.try_reserve(
            db, tenant_id=tenant_id, endpoint="create_invoice",
            idempotency_key=idempotency_key, request_hash=request_hash,
        )
        if outcome.is_replay:
            return InvoiceResponse.model_validate_json(outcome.cached_response)

        response = await _create_invoice_body(db, tenant_id=tenant_id, user_id=user_id, request=request)

        await idempotency_service.mark_completed_in_open_txn(
            db, tenant_id=tenant_id, row_id=outcome.row_id, response_json=response.model_dump_json(),
        )
    return response


async def _create_invoice_body(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    request: InvoiceCreateRequest,
) -> InvoiceResponse:
    """
    The only public function that takes care of entire invoice creation pipeline. 
    It is the longest function because invoice creation involves the most steps. 

    Operations in order:
      1.  Fetch tenant (state_code, annual_turnover) and validate party via
          party_service.validate_party_usable().
      2.  business_rules: validate buyer GSTIN format (defense-in-depth),
          determine place_of_supply.
      3.  tax_engine: determine_supply_type, then per-line
          calculate_taxable_value + calculate_line_item_tax.
      4.  tax_engine.aggregate_invoice_taxes → InvoiceTaxSummary.
      5.  ledger_rules.validate_invoice_arithmetic — declared vs computed.
      6.  If credit_note/debit_note:
            a. Fetch and validate original invoice (must exist, must be submitted)
            b. Fetch already-credited total
            c. ledger_rules.validate_credit_note_amount
      7.  business_rules.get_financial_year(invoice_date) → financial_year.
      8.  ATOMIC: sequence_service.get_next_invoice_number (FOR UPDATE) +
          invoice_repository.create + bulk_create_line_items.

    """
    # Gets the Tenant ORM object from token payload and Party ORM object from Database
    tenant = await tenant_repository.get_by_id(db, tenant_id=tenant_id)
    if tenant is None:
        raise TenantNotFoundError(str(tenant_id))

    compliance = await tenant_compliance_repository.get_active_for_tenant(
        db, tenant_id=tenant_id, as_of_date=request.invoice_date
    )
    annual_turnover = compliance.annual_turnover if compliance else Decimal("0")

    required_party_type = "vendor" if request.invoice_type == "purchase" else "customer"
    party = await party_repository.get_by_id(db, party_id=request.party_id, tenant_id=tenant_id)
    
    if party is None:
        raise PartyNotFoundError(str(request.party_id))
            
    if not party.is_active:                                  
        raise PartyInactiveError(str(request.party_id)) 
    
    if party.party_type != required_party_type:
        raise PartyTypeMismatchError(str(request.party_id), required_party_type)

    # BUSINESS RULES — GSTIN format check / determining PLACE OF SUPPLY
    if party.gstin is not None:
        if not business_rules.validate_gstin(party.gstin):
            raise InvalidGSTRateError(f"Party GSTIN '{party.gstin}' has an invalid format.")

    place_of_supply = business_rules.determine_place_of_supply(
        supplier_state_code=tenant.state_code,
        buyer_gstin=party.gstin,
        delivery_state_code=party.state_code,
        is_service=request.is_service,
    )
     
    # Tax Engine - Supply Type + per line calculation 
    supply_type = tax_engine.determine_supply_type(
        supplier_state_code=tenant.state_code,
        place_of_supply_state_code=place_of_supply
    )

    line_item_models: list[InvoiceItem] = []
    line_totals: list[Decimal] = []
    breakdowns: list[tax_engine.TaxBreakdown] = []
    gross_subtotal = ZERO
    total_line_discount = ZERO 

    for index,line_request in enumerate(request.line_items, start=1):
        _validate_line_item_business_rules(
            line_request=line_request,
            annual_turnover=annual_turnover,
            is_service=request.is_service 
        )

        line_gross = line_request.rate * line_request.quantity
        line_discount = _to_money(line_gross * line_request.discount_percent / ONE_HUNDRED)
        gross_subtotal += _to_money(line_gross)
        total_line_discount += line_discount

        taxable_value= tax_engine.calculate_taxable_amount(
            quantity=line_request.quantity,
            unit_price=line_request.rate,
            discount_amount=line_discount
        )

        breakdown= tax_engine.calculate_line_item_tax(
            taxable_value=taxable_value,
            gst_rate=line_request.gst_rate,
            supply_type=supply_type,
            cess_rate=line_request.cess_rate
        )

        breakdowns.append(breakdown)
        line_totals.append(breakdown.line_total)

        line_item_models.append(_build_line_item_model(
            tenant_id=tenant_id,
            line_number=index,
            line_request=line_request,
            taxable_value=taxable_value,
            line_discount=line_discount,
            breakdown=breakdown
        ))
    
    # Aggregate Tax calculation 
    tax_summary = tax_engine.aggregate_invoice_taxes(breakdowns)

    # Arithmetic Validation
    tolerance = Decimal("0.02") + (Decimal("0.05") * len(request.line_items))
    arithmetic_report = ledger_rules.validate_invoice_arithmetic(
        line_item_totals=line_totals,
        declared_grand_total=request.declared_grand_total,
        tolerance=tolerance
    )

    if not arithmetic_report.is_valid:
        raise InvoiceArithmeticError(
            expected=arithmetic_report.expected_grand_total,
            declared=arithmetic_report.declared_grand_total,
            discrepancy=arithmetic_report.discrepancy_amount,
        )
    
    # CREDIT/DEBIT NOTE VALIDATION
    if request.invoice_type in ("credit_note", "debit_note"):
        if request.invoice_type == "credit_note":
            # Lock the original so two concurrent credit notes against it
            # serialize. The second request waits here, then sees the first
            # one's credit note in the duplicate check below. Lock order
            # stays invoice -> sequence, same as record_payment.
            original = await invoice_repository.get_by_id_for_update(
                db, invoice_id=request.original_invoice_id, tenant_id=tenant_id,
            )
        else:
            original = await invoice_repository.get_by_id_with_line_items(
                db, invoice_id=request.original_invoice_id, tenant_id=tenant_id,
            )
        if original is None:
            raise OriginalInvoiceNotFoundError(str(request.original_invoice_id))

        if original.party_id != request.party_id:
            raise CreditNotePartyMismatchError(
                original_invoice_number=original.invoice_number,
                original_party_id=str(original.party_id),
                request_party_id=str(request.party_id),
            )

        if request.invoice_type == "credit_note":
            try:
                ledger_rules.validate_invoice_accepts_credit_note(
                    original.invoice_type, original.invoice_status, original.invoice_number,
                )
            except ValueError as exc:
                raise InvoiceNotCreditableError(str(exc)) from exc

            # HARD block, no override. Compares against payable_amount, the
            # value actually stored as total_amount.
            existing_cn = await invoice_repository.get_active_credit_note_for_original(
                db, tenant_id=tenant_id, original_invoice_id=original.id,
                amount=tax_summary.payable_amount,
            )
            if existing_cn is not None:
                raise DuplicateCreditNoteError(
                    original_invoice_number=original.invoice_number,
                    amount=tax_summary.payable_amount,
                    existing_credit_note_number=existing_cn.invoice_number,
                )
            already_credited = await invoice_repository.get_total_credited(
                db, original_invoice_id=original.id, tenant_id=tenant_id,
            )
            try:
                ledger_rules.validate_credit_note_amount(
                    credit_note_amount=tax_summary.payable_amount,
                    original_invoice_total=original.total_amount,
                    already_credited=already_credited,
                )
            except ValueError as exc:
                raise CreditNoteExceedsInvoiceError(str(exc)) from exc

    # SOFT duplicate check: sales, purchase and debit_note, overridable.
    if request.invoice_type != "credit_note" and not request.confirm_duplicate:
        similar = await invoice_repository.find_recent_similar_invoice(
            db, tenant_id=tenant_id, party_id=request.party_id,
            invoice_type=request.invoice_type, amount=tax_summary.payable_amount,
        )
        if similar is not None:
            minutes_ago = int((datetime.now(timezone.utc) - similar.created_at).total_seconds() // 60)
            elapsed = f"{minutes_ago} minute(s)" if minutes_ago < 60 else f"{minutes_ago // 60} hour(s)"
            raise PossibleDuplicateInvoiceError(
                party_id=str(request.party_id), amount=tax_summary.payable_amount,
                existing_invoice_number=similar.invoice_number, elapsed_display=elapsed,
            )
        
    # FINANCIAL YEAR 
    financial_year = business_rules.get_financial_year(request.invoice_date)
    
    # Atomic write
    invoice = await _create_invoice_atomic(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        request=request,
        party_gstin=party.gstin,
        party_state_code=party.state_code,
        supply_type=supply_type,
        place_of_supply=place_of_supply,
        financial_year=financial_year,
        tax_summary=tax_summary,
        gross_subtotal= gross_subtotal, 
        discount_amount = total_line_discount,
        line_item_models=line_item_models,
    )

    full_invoice = await invoice_repository.get_by_id_with_line_items(
        db, invoice_id=invoice.id, tenant_id=tenant_id,
    )

    return InvoiceResponse.model_validate(full_invoice)
    

def _validate_line_item_business_rules(
        *,
        line_request: LineItemCreate,
        annual_turnover: Decimal,
        is_service: bool
) -> None:
    """
    Runs business_rules validators that the Pydantic schema cannot perform
    because they require tenant context (annual_turnover) not present in
    the request body alone.
    """
    if not tax_engine.validate_gst_rate(line_request.gst_rate):
        raise InvalidGSTRateError(
            f"GST rate {line_request.gst_rate}% is not a valid statutory slab."
        )
    
    if line_request.hsn_sac_code is not None:
        if not business_rules.validate_hsn_sac_code(
            line_request.hsn_sac_code, annual_turnover, is_service=is_service,
        ):
            required = business_rules.get_required_hsn_digit_count(annual_turnover)
            raise InvalidHSNCodeError(
                f"HSN/SAC code '{line_request.hsn_sac_code}' is invalid. "
                f"Minimum {required or 2} digits required for this turnover."
            )
        
def _build_line_item_model(
        *, 
        tenant_id: UUID,
        line_number: int,
        line_request: LineItemCreate,
        taxable_value: Decimal,
        line_discount: Decimal,
        breakdown: tax_engine.TaxBreakdown,

) -> InvoiceItem:
    """
    Maps a validated LineItemCreate + computed TaxBreakdown into an
    InvoiceItem ORM instance. invoice_id is set later by SQLAlchemy's
    relationship cascade when the parent Invoice is added to the session
    via invoice.line_items.extend(...) — see _create_invoice_atomic.
    """
    return InvoiceItem(
        tenant_id=tenant_id,
        line_number=line_number,
        description=line_request.description,
        hsn_sac_code=line_request.hsn_sac_code,
        quantity=line_request.quantity,
        unit=line_request.unit or "PCS",
        rate=line_request.rate,
        discount_percent=line_request.discount_percent,
        discount_amount=line_discount,
        taxable_amount=taxable_value,
        gst_rate=breakdown.gst_rate,
        cgst_rate=breakdown.cgst_rate,
        cgst_amount=breakdown.cgst_amount,
        sgst_rate=breakdown.sgst_rate,
        sgst_amount=breakdown.sgst_amount,
        igst_rate=breakdown.igst_rate,
        igst_amount=breakdown.igst_amount,
        cess_rate=breakdown.cess_rate,
        cess_amount=breakdown.cess_amount
    )


async def _create_invoice_atomic(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        user_id: UUID,
        request: InvoiceCreateRequest,
        party_gstin: str | None,
        party_state_code: str,
        supply_type: str,
        place_of_supply: str,
        financial_year: str,
        tax_summary: tax_engine.InvoiceTaxSummary,
        gross_subtotal: Decimal, 
        discount_amount: Decimal, 
        line_item_models: list[InvoiceItem],
) -> Invoice:
    """
    Atomically: get_next_invoice_number (FOR UPDATE) + INSERT invoice + INSERT line items.

    Wrapped in async with db.begin() — all three succeed or all three roll back.
    There is never a partially-created invoice (header with no line items) or a
    sequence number incremented without a matching invoice row.

    IntegrityError retry: on the very first invoice for a (tenant, FY, type)
    combination, two concurrent requests may both find no sequence row and both
    attempt to INSERT it — the second INSERT raises IntegrityError on the
    composite PK. We catch IntegrityError and retry ONCE. The retry's
    SELECT FOR UPDATE now finds the row committed by the first request and
    proceeds normally via the increment path.
    
    """
    for attempt in range(2):
        try: 
            async with db.begin_nested():
                invoice_number = await sequence_service.get_next_invoice_number(
                    db,
                    tenant_id=tenant_id,
                    financial_year=financial_year,
                    invoice_type=request.invoice_type,
                )

                # reverse_charge: True when buyer has no GSTIN (unregistered dealer)
                reverse_charge = party_gstin is None
                

                invoice = await invoice_repository.create(
                    db,
                    tenant_id=tenant_id,
                    invoice_number=invoice_number,
                    invoice_type=request.invoice_type,
                    invoice_date=request.invoice_date,
                    due_date=request.due_date,
                    financial_year=financial_year,
                    party_id=request.party_id,
                    party_gstin=party_gstin,
                    party_state_code=party_state_code,
                    supply_type=supply_type,
                    place_of_supply=place_of_supply,
                    reverse_charge=reverse_charge,
                    subtotal=gross_subtotal, 
                    discount_amount=discount_amount,
                    taxable_amount=tax_summary.total_taxable_value,
                    cgst_amount=tax_summary.total_cgst,
                    sgst_amount=tax_summary.total_sgst,
                    igst_amount=tax_summary.total_igst,
                    cess_amount=tax_summary.total_cess,
                    total_amount=tax_summary.payable_amount,
                    notes=request.notes,
                    terms=request.terms,
                    original_invoice_id=request.original_invoice_id,
                    created_by=user_id,
                )

                for line_item in line_item_models:
                    line_item.invoice_id = invoice.id

                await invoice_repository.bulk_create_line_items(
                    db, line_items=line_item_models,
                )

            return invoice
        
        except IntegrityError as exc:
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint == "invoice_sequences_pkey" and attempt == 0:
                continue
            raise


async def get_invoice(
    db: AsyncSession,
    *,
    invoice_id: UUID,
    tenant_id: UUID,
) -> Invoice:
    """
    Fetch one invoice with line items. Raises InvoiceNotFoundError (404)
    if not found OR belongs to a different tenant — see Part 4 for why
    these two cases share one error code (information leakage prevention).
    """
    invoice = await invoice_repository.get_by_id_with_line_items(
        db, invoice_id=invoice_id, tenant_id=tenant_id,
    )
    if invoice is None:
        raise InvoiceNotFoundError(str(invoice_id))
    return invoice


async def send_invoice(
    db: AsyncSession,
    *,
    invoice_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    idempotency_key: str,
) -> InvoiceResponse:
    """
    Transition invoice from DRAFT to SUBMITTED. Locks the invoice forever.

    This is the most financially critical operation in the system.
    After this function succeeds:
    - invoice.status = 'submitted'
    - invoice.is_locked = True
    - invoice.locked_at = now
    - invoice.outstanding_amount = invoice.total_amount (becomes live AR receivable)

    For credit notes (invoice_type='credit_note'):
    - The credit note itself gets outstanding_amount = 0 (it's not a new receivable)
    - The original invoice's outstanding_amount is REDUCED by credit_note.total_amount
    - The original invoice's status may transition to 'paid' if outstanding → 0
    - Both updates happen in ONE transaction (credit note + original invoice)

    Concurrency safety:
    - SELECT FOR UPDATE on the invoice being submitted prevents two concurrent
      submissions of the same invoice from both succeeding.
    - For credit notes: also SELECT FOR UPDATE on the original invoice to prevent
      two concurrent credit note submissions from over-crediting.

    Triggers background tasks AFTER transaction commits:
    - send_invoice_email (default queue)
    - generate_invoice_pdf (reports queue)
    - invalidate_gst_report_cache (notifications queue)
    - refresh_dashboard_cache (notifications queue)
    """
    request_hash = str(invoice_id)   # no body — the invoice_id itself IS the request
    request_hash = hashlib.sha256(request_hash.encode("utf-8")).hexdigest()

    # STEP 1: LOCK AND VALIDATE
    async with db.begin():
        outcome = await idempotency_service.try_reserve(
            db, tenant_id=tenant_id, endpoint="send_invoice",
            idempotency_key=idempotency_key, request_hash=request_hash,
        )
        if outcome.is_replay:
            return InvoiceResponse.model_validate_json(outcome.cached_response)

        invoice = await invoice_repository.get_by_id_for_update(
            db, invoice_id=invoice_id, tenant_id=tenant_id
        )
        if invoice is None:
            raise InvoiceNotFoundError(str(invoice_id))

        # Must be DRAFT to submit
        try:
            ledger_rules.validate_invoice_is_mutable(invoice.invoice_status, invoice.invoice_number)
        except ValueError as exc:
            raise InvoiceLockedError(str(exc))

        # Validate the auto-generated invoice number format (defense-in-depth)
        if not business_rules.validate_invoice_number_format(invoice.invoice_number):
            raise InvalidInvoiceNumberError(invoice.invoice_number)

        # STEP 2: DETERMINE outstanding_amount 
        if invoice.invoice_type == "credit_note":
            # Lock and update original invoice
            await _apply_credit_note_to_original(
                db,
                original_invoice_id=invoice.original_invoice_id,
                tenant_id=tenant_id,
                credit_note_total=invoice.total_amount,
                user_id=user_id,
            )

            await invoice_repository.update_submission_state(
                db,
                invoice_id=invoice_id,
                tenant_id=tenant_id,
                updated_by=user_id,
                paid_amount=invoice.total_amount,
            )

        else:
            # Sales / debit note / purchase: outstanding = total_amount
            await invoice_repository.update_submission_state(
                db,
                invoice_id=invoice_id,
                tenant_id=tenant_id,
                updated_by=user_id,
            )

        full_invoice = await invoice_repository.get_by_id_with_line_items(db, invoice_id=invoice_id, tenant_id=tenant_id)
        response = InvoiceResponse.model_validate(full_invoice)

        await idempotency_service.mark_completed_in_open_txn(
            db, tenant_id=tenant_id, row_id=outcome.row_id, response_json=response.model_dump_json(),
        )

    # STEP 3: TRIGGER BACKGROUND TASKS (after transaction commits)
    _enqueue_submission_tasks(
        invoice_id=str(invoice_id),
        tenant_id=str(tenant_id),
        invoice_type=invoice.invoice_type,
    )

    # Re-fetch with line_items for the response
    return response


def _enqueue_submission_tasks(*, invoice_id: str, tenant_id: str, invoice_type: str) -> None:
    """
    Fires background work (email, PDF, cache invalidation — see
    send_invoice's docstring) AFTER commit, same rule as every other
    _enqueue_* stub in this project. Stub for now.
    """
    pass


async def _apply_credit_note_to_original(
    db: AsyncSession,
    *,
    original_invoice_id: UUID,
    tenant_id: UUID,
    credit_note_total: Decimal,
    user_id: UUID,
) -> None:
    """
    Reduce the original invoice's outstanding_amount by the credit note total.

    Called inside send_invoice's transaction when invoice_type='credit_note'.
    SELECT FOR UPDATE on the original invoice prevents two concurrent credit
    note submissions from both reading the same outstanding_amount and
    over-crediting.

    New status is derived from the new outstanding:
    - outstanding == 0 and paid_amount > 0 → 'paid'
    - outstanding == 0 and paid_amount == 0 → 'paid' (fully credited)
    - outstanding > 0 → 'sent' (still has receivable)
    """
    # Lock the original invoice row
    original = await invoice_repository.get_by_id_for_update(
        db, invoice_id=original_invoice_id, tenant_id=tenant_id
    )
    if original is None:
        raise OriginalInvoiceNotFoundError(str(original_invoice_id))

    # Recheck under the lock. The original may have been voided or fully
    # paid between this credit note's creation and its submission.
    try:
        ledger_rules.validate_invoice_accepts_credit_note(
            original.invoice_type, original.invoice_status, original.invoice_number,
        )
    except ValueError as exc:
        raise InvoiceNotCreditableError(str(exc)) from exc

    try:
        allocation = ledger_rules.allocate_payment(
            invoice_total=original.total_amount,
            previously_paid=original.paid_amount,
            new_payment=credit_note_total,
        )
    except ValueError as exc:
        raise CreditNoteExceedsInvoiceError(str(exc)) from exc

    await invoice_repository.update_payment_state(
        db, invoice_id=original_invoice_id, tenant_id=tenant_id,
        paid_amount=allocation.total_paid_after,
        status=allocation.new_status,
        updated_by=user_id,
    )


async def void_invoice(
    db: AsyncSession,
    *,
    invoice_id: UUID,
    tenant_id: UUID,
    voided_by: UUID,
    void_reason: str,
) -> Invoice:
    """
    Transitions a "sent" invoice with zero payments to 'void'. Never
    deleted — a permanent audit-trail entry, same pattern as
    payment_service.cancel_payment.

    Deliberately no idempotency layer: a retry lands on the same
    invoice_id and converges naturally on InvoiceNotVoidableError
    (invoice_status is no longer "sent" after the first success), same
    reasoning as cancel_payment's lack of one.
    """
    async with db.begin():
        invoice = await invoice_repository.get_by_id_for_update(
            db, invoice_id=invoice_id, tenant_id=tenant_id,
        )
        if invoice is None:
            raise InvoiceNotFoundError(str(invoice_id))

        try:
            ledger_rules.validate_invoice_is_voidable(
                invoice.invoice_status, invoice.paid_amount, invoice.invoice_number,
            )
        except ValueError as exc:
            raise InvoiceNotVoidableError(
                invoice_number=invoice.invoice_number,
                current_status=invoice.invoice_status,
                paid_amount=invoice.paid_amount,
            ) from exc

        await invoice_repository.update_void_state(
            db, invoice_id=invoice_id, tenant_id=tenant_id,
            voided_by=voided_by, void_reason=void_reason,
        )

    return await get_invoice(db, invoice_id=invoice_id, tenant_id=tenant_id)


async def fetch_invoice(
    db: AsyncSession, *, invoice_id: UUID, tenant_id: UUID,
) -> InvoiceResponse:
    """Read one invoice with line items inside its own short transaction."""
    async with db.begin():
        invoice = await get_invoice(db, invoice_id=invoice_id, tenant_id=tenant_id)
    return InvoiceResponse.model_validate(invoice)


async def list_invoices(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    status: str | None,
    invoice_type: str | None,
    party_id: UUID | None,
    date_from: date | None,
    date_to: date | None,
    cursor: str | None,
    limit: int,
) -> Page[InvoiceSummaryResponse]:
    """Cursor-paginated invoice list, newest first."""
    if date_from is not None and date_to is not None and date_from > date_to:
        raise InvalidListQueryError("date_from cannot be after date_to.")
    after = decode_date_cursor(cursor)

    async with db.begin():
        rows = await invoice_repository.list_page(
            db, tenant_id=tenant_id, status=status, invoice_type=invoice_type,
            party_id=party_id, date_from=date_from, date_to=date_to,
            after=after, limit=limit + 1,
        )

    page_rows = rows[:limit]
    items = [
        InvoiceSummaryResponse.model_validate(invoice).model_copy(update={"party_name": party_name})
        for invoice, party_name in page_rows
    ]
    next_cursor = None
    if len(rows) > limit:
        last_invoice = page_rows[-1][0]
        next_cursor = encode_cursor(last_invoice.invoice_date.isoformat(), last_invoice.id)
    return Page[InvoiceSummaryResponse](items=items, next_cursor=next_cursor)