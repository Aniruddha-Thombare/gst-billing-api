from uuid import UUID

from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.core.pagination import Page, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.database import get_db
from app.models.enum import UserRole, PartyType
from app.schemas.auth import TokenPayload
from app.schemas.party import PartyCreateRequest, PartyResponse, PartyUpdateRequest
from app.services import party_service

router = APIRouter(prefix="/parties", tags=["Parties"])

_WRITE_ROLES = ("owner", "accountant")
_READ_ROLES = tuple(role.value for role in UserRole)


@router.post(
    "",
    response_model=PartyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a customer or vendor",
)
async def create_party(
    request: PartyCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role(*_WRITE_ROLES)),
) -> PartyResponse:
    """
    Permission: owner, accountant.
    Errors: 409 duplicate GSTIN, 422 invalid GSTIN / state / PAN mismatch.
    """
    party = await party_service.create_party(
        db, tenant_id=current_user.tenant_id, user_id=current_user.sub, request=request,
    )
    return PartyResponse.model_validate(party)


@router.get(
    "",
    response_model=Page[PartyResponse],
    summary="List customers and vendors (alphabetical, cursor pagination)",
)
async def list_parties(
    party_type: PartyType | None = None,
    is_active: bool | None = None,
    name: str | None = Query(default=None, max_length=100, description="Name starts with (case-insensitive)"),
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role(*_READ_ROLES)),
) -> Page[PartyResponse]:
    """Permission: any role. 'List customers' is party_type=customer."""
    return await party_service.list_parties(
        db, tenant_id=current_user.tenant_id,
        party_type=party_type.value if party_type else None,
        is_active=is_active, name_prefix=name, cursor=cursor, limit=limit,
    )


@router.get(
    "/{party_id}",
    response_model=PartyResponse,
    summary="Get one party",
)
async def get_party(
    party_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role(*_READ_ROLES)),
) -> PartyResponse:
    """Permission: any role. 404 if missing or belongs to another tenant."""
    party = await party_service.get_party(
        db, party_id=party_id, tenant_id=current_user.tenant_id,
    )
    return PartyResponse.model_validate(party)


@router.put(
    "/{party_id}",
    response_model=PartyResponse,
    summary="Update a party (full replace of editable fields)",
)
async def update_party(
    party_id: UUID,
    request: PartyUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role(*_WRITE_ROLES)),
) -> PartyResponse:
    """
    Permission: owner, accountant. party_type cannot be changed.
    Issued invoices keep their frozen snapshot and are not affected.
    """
    party = await party_service.update_party(
        db, party_id=party_id, tenant_id=current_user.tenant_id,
        user_id=current_user.sub, request=request,
    )
    return PartyResponse.model_validate(party)


@router.post(
    "/{party_id}/deactivate",
    response_model=PartyResponse,
    summary="Deactivate a party (blocks new invoices)",
)
async def deactivate_party(
    party_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role(*_WRITE_ROLES)),
) -> PartyResponse:
    """Permission: owner, accountant. Existing invoices and payments are unaffected."""
    party = await party_service.set_party_active(
        db, party_id=party_id, tenant_id=current_user.tenant_id,
        user_id=current_user.sub, is_active=False,
    )
    return PartyResponse.model_validate(party)


@router.post(
    "/{party_id}/activate",
    response_model=PartyResponse,
    summary="Reactivate a party",
)
async def activate_party(
    party_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role(*_WRITE_ROLES)),
) -> PartyResponse:
    """Permission: owner, accountant."""
    party = await party_service.set_party_active(
        db, party_id=party_id, tenant_id=current_user.tenant_id,
        user_id=current_user.sub, is_active=True,
    )
    return PartyResponse.model_validate(party)