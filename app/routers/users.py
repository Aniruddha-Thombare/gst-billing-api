from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.database import get_db
from app.schemas.auth import TokenPayload
from app.schemas.user_admin import (
    ChangePasswordRequest, UserCreateRequest, UserResponse, UserRoleUpdateRequest,
)
from app.services import user_admin_service

router = APIRouter(prefix="/users", tags=["Users"])

_OWNER = require_role("owner")
_ANY_ROLE = require_role("owner", "accountant", "viewer", "auditor")


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: UserCreateRequest, db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(_OWNER),
):
    return await user_admin_service.create_user(
        db, tenant_id=current_user.tenant_id, actor_id=UUID(str(current_user.sub)), request=request,
    )


@router.get("", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db), current_user: TokenPayload = Depends(_OWNER),
):
    return await user_admin_service.list_users(db, tenant_id=current_user.tenant_id)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_my_password(
    request: ChangePasswordRequest, db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(_ANY_ROLE),
):
    await user_admin_service.change_own_password(
        db, tenant_id=current_user.tenant_id, user_id=UUID(str(current_user.sub)), request=request,
    )


@router.patch("/{user_id}/role", response_model=UserResponse)
async def change_user_role(
    user_id: UUID, request: UserRoleUpdateRequest, db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(_OWNER),
):
    return await user_admin_service.change_role(
        db, tenant_id=current_user.tenant_id, actor_id=UUID(str(current_user.sub)),
        user_id=user_id, request=request,
    )


@router.post("/{user_id}/deactivate", response_model=UserResponse)
async def deactivate_user(
    user_id: UUID, db: AsyncSession = Depends(get_db), current_user: TokenPayload = Depends(_OWNER),
):
    return await user_admin_service.set_user_active(
        db, tenant_id=current_user.tenant_id, actor_id=UUID(str(current_user.sub)),
        user_id=user_id, is_active=False,
    )


@router.post("/{user_id}/activate", response_model=UserResponse)
async def activate_user(
    user_id: UUID, db: AsyncSession = Depends(get_db), current_user: TokenPayload = Depends(_OWNER),
):
    return await user_admin_service.set_user_active(
        db, tenant_id=current_user.tenant_id, actor_id=UUID(str(current_user.sub)),
        user_id=user_id, is_active=True,
    )