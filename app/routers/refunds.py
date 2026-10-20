from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.database import get_db
from app.models.enum import UserRole
from app.schemas.auth import TokenPayload
from app.schemas.refund import RefundCreateRequest, RefundRecordedResponse, RefundResponse, RefundCancelRequest
from app.services import refund_service

router = APIRouter(prefix="/invoices", tags=["refunds"])

refunds_router = APIRouter(prefix="/refunds", tags=["refunds"])


_READ_ROLES = tuple(role.value for role in UserRole)


@router.post(
    "/{invoice_id}/refunds",
    response_model=RefundRecordedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a refund paid to the customer",
)
async def record_refund(
    invoice_id: UUID,
    request: RefundCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role("owner", "accountant")),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
) -> RefundRecordedResponse:
    """
    Permission: owner, accountant. Idempotency-Key required.
    The amount cannot exceed the invoice's refund_due_amount (422 REFUND_EXCEEDS_DUE).
    """
    return await refund_service.record_refund(
        db, tenant_id=current_user.tenant_id, user_id=current_user.sub,
        invoice_id=invoice_id, request=request, idempotency_key=idempotency_key,
    )


@router.get(
    "/{invoice_id}/refunds",
    response_model=list[RefundResponse],
    summary="List refunds of one invoice",
)
async def list_refunds(
    invoice_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role(*_READ_ROLES)),
) -> list[RefundResponse]:
    """Permission: any role. Includes cancelled refunds."""
    return await refund_service.list_refunds(
        db, invoice_id=invoice_id, tenant_id=current_user.tenant_id,
    )


@refunds_router.post(
    "/{refund_id}/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-cancel a refund and restore the invoice's refund due",
)
async def cancel_refund(
    refund_id: UUID,
    request: RefundCancelRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role("owner", "accountant")),
) -> None:
    """
    Cancels a refund recorded in error or one that did not go through (for
    example a bounced transfer). The row is never deleted. The invoice's
    refunded_amount and refund_due_amount are recomputed from source rows.

    No Idempotency-Key: a retry converges on 409 REFUND_ALREADY_CANCELLED.
    Errors: 404 not found (or other tenant), 409 already cancelled,
    422 reason too short, 403 role.
    """
    await refund_service.cancel_refund(
        db, tenant_id=current_user.tenant_id, cancelled_by=current_user.sub,
        refund_id=refund_id, cancellation_reason=request.cancellation_reason,
    )