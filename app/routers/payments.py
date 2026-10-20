from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page
from app.database import get_db
from app.models.enum import UserRole
from app.schemas.auth import TokenPayload
from app.schemas.payment import (
    PaymentCancelRequest,
    PaymentCreateRequest,
    PaymentRecordedResponse,
    PaymentResponse,
)
from app.services import payment_service


# Routes that live under /invoices/{invoice_id}/...
invoice_payments_router = APIRouter(
    prefix="/invoices",
    tags=["payments"],
)

# Routes that live under /payments/...
payments_router = APIRouter(
    prefix="/payments",
    tags=["payments"],
)

_READ_ROLES = tuple(role.value for role in UserRole)


@invoice_payments_router.post(
    "/{invoice_id}/payments",
    response_model=PaymentRecordedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record Customer Payment for a Submitted Invoice",
)
async def record_payment(
    invoice_id: UUID,
    request: PaymentCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role("owner", "accountant")),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
) -> PaymentRecordedResponse:
    """
    Record a customer payment against a submitted invoice.
    Permission: owner, accountant. viewer cannot record payments (read-only).

    Idempotency-Key is REQUIRED. Clients must generate a fresh UUID per new
    payment attempt and reuse the SAME key on retry (timeout, network error,
    double-click). A missing header returns 422 before this function runs.

    Returns the payment record PLUS the resulting invoice ledger state, so
    the client can update its UI without a second round trip.
    """
    return await payment_service.record_payment(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.sub,
        invoice_id=invoice_id,
        request=request,
        idempotency_key=idempotency_key,
    )


@payments_router.get(
    "",
    response_model=Page[PaymentResponse],
    summary="List payments (newest first, cursor pagination)",
)
async def list_payments(
    invoice_id: UUID | None = None,
    payment_status: str | None = Query(
        default=None, alias="status", pattern=r"^(active|cancelled)$",
    ),
    date_from: date | None = None,
    date_to: date | None = None,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role(*_READ_ROLES)),
) -> Page[PaymentResponse]:
    """
    Permission: any role.

    Filter by invoice_id to get one invoice's payments. Cancelled payments
    are included unless status=active is passed. Pass the previous
    response's next_cursor as cursor to get the next page.
    """
    return await payment_service.list_payments(
        db,
        tenant_id=current_user.tenant_id,
        invoice_id=invoice_id,
        status=payment_status,
        date_from=date_from,
        date_to=date_to,
        cursor=cursor,
        limit=limit,
    )


@payments_router.post(
    "/{payment_id}/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-cancel a payment and restore the invoice's ledger state",
)
async def cancel_payment(
    payment_id: UUID,
    request: PaymentCancelRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role("owner", "accountant")),
) -> None:
    """
    Cancels a payment recorded in error (wrong invoice, duplicate entry,
    wrong amount). The payment row is NEVER deleted: it is marked
    status='cancelled' and stays permanently for audit. The invoice's
    paid/outstanding balance is recomputed from remaining active payments
    plus applied credit notes, not by arithmetic subtraction.

    No Idempotency-Key here: a retry of this exact request converges on
    PaymentAlreadyCancelledError (409) rather than double-processing.

    Returns 204 No Content on success.

    Error responses:
    - 404: Payment not found (or belongs to a different tenant)
    - 409: Payment already cancelled
    - 422: cancellation_reason missing or too short
    - 403: Insufficient role
    """
    await payment_service.cancel_payment(
        db,
        tenant_id=current_user.tenant_id,
        cancelled_by=current_user.sub,
        payment_id=payment_id,
        cancellation_reason=request.cancellation_reason,
    )