from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.db_errors import get_constraint_name
from app.core.exceptions import (
    CurrentPasswordIncorrectError, DuplicateEmailError, UserManagementNotAllowedError,
    UserNotFoundError,
)
from app.domain import user_access_rules
from app.models.enum import AuditAction, EntityType, UserRole
from app.repositories import user_admin_repository, user_repository
from app.schemas.user_admin import (
    ChangePasswordRequest, UserCreateRequest, UserResponse, UserRoleUpdateRequest,
)
from app.services import audit_service


def _enforce(check, **kwargs) -> None:
    try:
        check(**kwargs)
    except ValueError as exc:
        raise UserManagementNotAllowedError(str(exc)) from exc


async def _get_target_for_update(db: AsyncSession, *, tenant_id: UUID, user_id: UUID):
    target = await user_admin_repository.get_by_id(
        db, tenant_id=tenant_id, user_id=user_id, for_update=True,
    )
    if target is None:
        raise UserNotFoundError(str(user_id))
    return target


async def create_user(
    db: AsyncSession, *, tenant_id: UUID, actor_id: UUID, request: UserCreateRequest,
) -> UserResponse:
    _enforce(user_access_rules.validate_role_assignable, role=request.role)
    email = request.email.lower()
    # bcrypt is CPU-heavy: hash in a thread, before any DB transaction opens.
    hashed_password = await asyncio.to_thread(security.hash_password, request.password)

    try:
        async with db.begin():
            if await user_repository.get_by_email(db, email=email):
                raise DuplicateEmailError(email)
            user = await user_repository.create(
                db, tenant_id=tenant_id, email=email, hashed_password=hashed_password,
                full_name=request.full_name.strip(), role=UserRole(request.role),
            )
            await audit_service.record(
                db, tenant_id=tenant_id, user_id=actor_id,
                entity_type=EntityType.USER, entity_id=user.id, action=AuditAction.CREATE,
                new_values={"email": email, "full_name": request.full_name.strip(), "role": request.role},
            )
            response = UserResponse.model_validate(user)
    except IntegrityError as exc:
        if get_constraint_name(exc) in ("uq_user_email", "uq_tenant_email"):
            raise DuplicateEmailError(email) from exc
        raise
    return response


async def list_users(db: AsyncSession, *, tenant_id: UUID) -> list[UserResponse]:
    async with db.begin():
        rows = await user_admin_repository.list_for_tenant(db, tenant_id=tenant_id)
        return [UserResponse.model_validate(row) for row in rows]


async def change_role(
    db: AsyncSession, *, tenant_id: UUID, actor_id: UUID, user_id: UUID,
    request: UserRoleUpdateRequest,
) -> UserResponse:
    async with db.begin():
        target = await _get_target_for_update(db, tenant_id=tenant_id, user_id=user_id)
        _enforce(user_access_rules.validate_target_manageable,
                 actor_id=actor_id, target_id=user_id, target_role=target.role)
        _enforce(user_access_rules.validate_role_assignable, role=request.role)

        old_role = getattr(target.role, "value", target.role)
        if old_role != request.role:
            await user_admin_repository.set_role(db, user=target, role=UserRole(request.role))
            await audit_service.record(
                db, tenant_id=tenant_id, user_id=actor_id,
                entity_type=EntityType.USER, entity_id=user_id, action=AuditAction.UPDATE,
                old_values={"role": old_role}, new_values={"role": request.role},
            )
        return UserResponse.model_validate(target)


async def set_user_active(
    db: AsyncSession, *, tenant_id: UUID, actor_id: UUID, user_id: UUID, is_active: bool,
) -> UserResponse:
    async with db.begin():
        target = await _get_target_for_update(db, tenant_id=tenant_id, user_id=user_id)
        _enforce(user_access_rules.validate_target_manageable,
                 actor_id=actor_id, target_id=user_id, target_role=target.role)

        was_active = target.is_active
        if was_active != is_active:
            await user_admin_repository.set_active(db, user=target, is_active=is_active)
            await audit_service.record(
                db, tenant_id=tenant_id, user_id=actor_id,
                entity_type=EntityType.USER, entity_id=user_id,
                action=AuditAction.ACTIVATE if is_active else AuditAction.DEACTIVATE,
                old_values={"is_active": was_active}, new_values={"is_active": is_active},
            )
        return UserResponse.model_validate(target)


async def change_own_password(
    db: AsyncSession, *, tenant_id: UUID, user_id: UUID, request: ChangePasswordRequest,
) -> None:
    async with db.begin():
        user = await user_admin_repository.get_by_id(db, tenant_id=tenant_id, user_id=user_id)
        if user is None:
            raise UserNotFoundError(str(user_id))
        current_hash = user.hashed_password

    current_ok = await asyncio.to_thread(security.verify_password, request.current_password, current_hash)
    if not current_ok:
        raise CurrentPasswordIncorrectError()
    new_hash = await asyncio.to_thread(security.hash_password, request.new_password)

    async with db.begin():
        user = await _get_target_for_update(db, tenant_id=tenant_id, user_id=user_id)
        await user_admin_repository.set_password_hash(db, user=user, hashed_password=new_hash)
        await audit_service.record(
            db, tenant_id=tenant_id, user_id=user_id,
            entity_type=EntityType.USER, entity_id=user_id, action=AuditAction.UPDATE,
            new_values={"credential_changed": True},
        )