from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.core.pagination import Page
from app.database import get_db
from app.schemas.auth import TokenPayload
from app.schemas.item import ItemCreateRequest, ItemResponse, ItemUpdateRequest
from app.services import item_service

router = APIRouter(prefix="/items", tags=["Items"])

_WRITERS = require_role("owner", "accountant")
_READERS = require_role("owner", "accountant", "viewer")


@router.post("", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(
    request: ItemCreateRequest, db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(_WRITERS),
):
    return await item_service.create_item(
        db, tenant_id=current_user.tenant_id, user_id=UUID(str(current_user.sub)), request=request,
    )


@router.get("", response_model=Page[ItemResponse])
async def list_items(
    is_active: bool | None = None, name_prefix: str | None = Query(default=None, max_length=100),
    cursor: str | None = None, limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db), current_user: TokenPayload = Depends(_READERS),
):
    return await item_service.list_items(
        db, tenant_id=current_user.tenant_id, is_active=is_active,
        name_prefix=name_prefix, cursor=cursor, limit=limit,
    )


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(
    item_id: UUID, db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(_READERS),
):
    return await item_service.get_item(db, item_id=item_id, tenant_id=current_user.tenant_id)


@router.put("/{item_id}", response_model=ItemResponse)
async def update_item(
    item_id: UUID, request: ItemUpdateRequest, db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(_WRITERS),
):
    return await item_service.update_item(
        db, item_id=item_id, tenant_id=current_user.tenant_id,
        user_id=UUID(str(current_user.sub)), request=request,
    )


@router.post("/{item_id}/deactivate", response_model=ItemResponse)
async def deactivate_item(
    item_id: UUID, db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(_WRITERS),
):
    return await item_service.set_item_active(
        db, item_id=item_id, tenant_id=current_user.tenant_id,
        user_id=UUID(str(current_user.sub)), is_active=False,
    )


@router.post("/{item_id}/activate", response_model=ItemResponse)
async def activate_item(
    item_id: UUID, db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(_WRITERS),
):
    return await item_service.set_item_active(
        db, item_id=item_id, tenant_id=current_user.tenant_id,
        user_id=UUID(str(current_user.sub)), is_active=True,
    )