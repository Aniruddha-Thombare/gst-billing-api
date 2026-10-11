from uuid import UUID
from datetime import date 
from fastapi import APIRouter, status, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.core.pagination import Page, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.schemas.auth import TokenPayload
from app.schemas.invoice import (
    InvoiceCreateRequest, InvoiceResponse, InvoiceVoidRequest, InvoiceSummaryResponse
)
from app.models.enum import InvoiceStatus, InvoiceType, UserRole
from app.database import get_db
from app.services import invoice_service


router = APIRouter(
    prefix="/invoices",
    tags=["Invoices"]
)

_READ_ROLES = tuple(role.value for role in UserRole)

@router.post(
    "/create_invoice",
    response_model=InvoiceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an invoice, debit note or credit note"
)
async def create_invoice(
    request:InvoiceCreateRequest,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
    current_user: TokenPayload = Depends(require_role("owner", "accountant")),
)-> InvoiceResponse:
    """
    Once the User hit the request for invoice creation, credit note and debit note on 
    this endpoint - this function gets triggered. 
    The only job of this func is that it takes the user request for Invoice creation, 
    checks the current_user role matches the require role criteria - then gets the 
    token payload, does the pydantic validation against request schema and calls the 
    invoice service for invoice creation and returns the InvoiceResponse class object. 
    """
    return await invoice_service.create_invoice(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.sub,
        request=request,
        idempotency_key=idempotency_key
    )


@router.post(
    "/{invoice_id}/send",
    response_model=InvoiceResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit invoice — transitions DRAFT → SUBMITTED (legally locked)",
)
async def send_invoice(
    invoice_id: UUID,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
    current_user: TokenPayload = Depends(require_role("owner", "accountant")),
) -> InvoiceResponse:
    """
    Permission: owner, accountant.

    Submits the invoice. After this succeeds:
    - Invoice is legally locked (is_locked=True, immutable forever)
    - outstanding_amount is set to total_amount (becomes live AR receivable)
    - AR, aging, and GST reports now include this invoice
    - Background tasks triggered: email, PDF, cache invalidation

    For credit notes:
    - Credit note's own outstanding_amount = 0
    - Original invoice's outstanding_amount is reduced by this credit note's total
    - Original invoice may transition to 'paid' if outstanding reaches 0

    A submitted invoice with no payments recorded can still be voided
    (see POST /invoices/{invoice_id}/void). A submitted invoice with any
    payment recorded, or one already voided, cannot be further edited.
    """
    return await invoice_service.send_invoice(
        db,
        invoice_id=invoice_id,
        tenant_id=current_user.tenant_id,
        user_id=current_user.sub,
        idempotency_key=idempotency_key
    )


@router.post(
    "/{invoice_id}/void",
    response_model=InvoiceResponse,
    status_code=status.HTTP_200_OK,
    summary="Void an unpaid, submitted invoice",
)
async def void_invoice(
    invoice_id: UUID,
    request: InvoiceVoidRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role("owner", "accountant")),
) -> InvoiceResponse:
    """
    Permission: owner, accountant.

    Voids an invoice issued in error — wrong customer, duplicate, wrong
    amount — before any payment was received. The invoice row is NEVER
    deleted; it is marked invoice_status='void' with a permanent audit
    trail (voided_at, voided_by, void_reason).

    Only invoices in 'sent' status with paid_amount == 0 qualify. An
    invoice with any payment recorded against it must be corrected with
    a Credit Note instead — voiding it would orphan the payment.

    Error responses:
    - 404: Invoice not found (or belongs to a different tenant)
    - 422: Invoice not in a voidable state (InvoiceNotVoidableError)
    - 422: void_reason missing or too short (schema validation)
    - 403: Insufficient role
    """
    invoice = await invoice_service.void_invoice(
        db,
        invoice_id=invoice_id,
        tenant_id=current_user.tenant_id,
        voided_by=current_user.sub,
        void_reason=request.void_reason,
    )
    return InvoiceResponse.model_validate(invoice)   


_READ_ROLES = tuple(role.value for role in UserRole)


@router.get(
    "",
    response_model=Page[InvoiceSummaryResponse],
    summary="List invoices (newest first, cursor pagination)",
)
async def list_invoices(
    invoice_status: InvoiceStatus | None = Query(default=None, alias="status"),
    invoice_type: InvoiceType | None = None,
    party_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role(*_READ_ROLES)),
) -> Page[InvoiceSummaryResponse]:
    """Permission: any role. Pass the previous response's next_cursor to get the next page."""
    return await invoice_service.list_invoices(
        db,
        tenant_id=current_user.tenant_id,
        status=invoice_status.value if invoice_status else None,
        invoice_type=invoice_type.value if invoice_type else None,
        party_id=party_id, date_from=date_from, date_to=date_to,
        cursor=cursor, limit=limit,
    )


@router.get(
    "/{invoice_id}",
    response_model=InvoiceResponse,
    summary="Get one invoice with line items",
)
async def get_invoice(
    invoice_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role(*_READ_ROLES)),
) -> InvoiceResponse:
    """Permission: any role. 404 if missing or belongs to another tenant."""
    return await invoice_service.fetch_invoice(
        db, invoice_id=invoice_id, tenant_id=current_user.tenant_id,
    )