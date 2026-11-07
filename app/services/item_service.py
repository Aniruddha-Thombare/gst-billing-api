from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_errors import get_constraint_name
from app.core.exceptions import DuplicateItemNameError, InvalidItemError, ItemNotFoundError
from app.core.pagination import Page, decode_cursor, encode_cursor
from app.domain import tax_engine
from app.models.enum import AuditAction, EntityType
from app.repositories import item_repository
from app.schemas.item import ItemCreateRequest, ItemResponse, ItemUpdateRequest
from app.services import audit_service

_UNIQUE_NAME_INDEX = "uq_items_tenant_name_lower"


def _editable_values(request: ItemCreateRequest | ItemUpdateRequest) -> dict[str, object]:
    return {
        "name": request.name, "hsn_sac_code": request.hsn_sac_code, "unit": request.unit,
        "rate": request.rate, "gst_rate": request.gst_rate, "cess_rate": request.cess_rate,
        "is_service": request.is_service,
    }


def _validate_item_rules(request: ItemCreateRequest | ItemUpdateRequest) -> None:
    if not tax_engine.validate_gst_rate(request.gst_rate):
        raise InvalidItemError(f"GST rate {request.gst_rate}% is not a valid statutory slab.")


def _raise_if_duplicate_name(exc: IntegrityError, name: str) -> None:
    if get_constraint_name(exc) == _UNIQUE_NAME_INDEX:
        raise DuplicateItemNameError(name) from exc


async def create_item(
    db: AsyncSession, *, tenant_id: UUID, user_id: UUID, request: ItemCreateRequest,
) -> ItemResponse:
    _validate_item_rules(request)
    values = _editable_values(request)
    try:
        async with db.begin():
            item = await item_repository.create(db, tenant_id=tenant_id, created_by=user_id, **values)
            await audit_service.record(
                db, tenant_id=tenant_id, user_id=user_id,
                entity_type=EntityType.CATALOG_ITEM, entity_id=item.id,
                action=AuditAction.CREATE, new_values=values,
            )
            response = ItemResponse.model_validate(item)
    except IntegrityError as exc:
        _raise_if_duplicate_name(exc, request.name)
        raise
    return response


async def get_item(db: AsyncSession, *, item_id: UUID, tenant_id: UUID) -> ItemResponse:
    async with db.begin():
        item = await item_repository.get_by_id(db, item_id=item_id, tenant_id=tenant_id)
        if item is None:
            raise ItemNotFoundError(str(item_id))
        return ItemResponse.model_validate(item)


async def update_item(
    db: AsyncSession, *, item_id: UUID, tenant_id: UUID, user_id: UUID, request: ItemUpdateRequest,
) -> ItemResponse:
    """Only fields that actually changed are written to the audit trail."""
    _validate_item_rules(request)
    values = _editable_values(request)
    try:
        async with db.begin():
            item = await item_repository.get_by_id(
                db, item_id=item_id, tenant_id=tenant_id, for_update=True,
            )
            if item is None:
                raise ItemNotFoundError(str(item_id))
            old_snapshot = {key: getattr(item, key) for key in values}
            await item_repository.apply_values(db, item=item, values=values, updated_by=user_id)

            changed = [key for key in values if old_snapshot[key] != values[key]]
            if changed:
                await audit_service.record(
                    db, tenant_id=tenant_id, user_id=user_id,
                    entity_type=EntityType.CATALOG_ITEM, entity_id=item_id, action=AuditAction.UPDATE,
                    old_values={key: old_snapshot[key] for key in changed},
                    new_values={key: values[key] for key in changed},
                )
            response = ItemResponse.model_validate(item)
    except IntegrityError as exc:
        _raise_if_duplicate_name(exc, request.name)
        raise
    return response


async def set_item_active(
    db: AsyncSession, *, item_id: UUID, tenant_id: UUID, user_id: UUID, is_active: bool,
) -> ItemResponse:
    async with db.begin():
        item = await item_repository.get_by_id(
            db, item_id=item_id, tenant_id=tenant_id, for_update=True,
        )
        if item is None:
            raise ItemNotFoundError(str(item_id))
        was_active = item.is_active
        if was_active != is_active:
            await item_repository.set_active(db, item=item, is_active=is_active, updated_by=user_id)
            await audit_service.record(
                db, tenant_id=tenant_id, user_id=user_id,
                entity_type=EntityType.CATALOG_ITEM, entity_id=item_id,
                action=AuditAction.ACTIVATE if is_active else AuditAction.DEACTIVATE,
                old_values={"is_active": was_active}, new_values={"is_active": is_active},
            )
        return ItemResponse.model_validate(item)


async def list_items(
    db: AsyncSession, *, tenant_id: UUID, is_active: bool | None,
    name_prefix: str | None, cursor: str | None, limit: int,
) -> Page[ItemResponse]:
    after = decode_cursor(cursor)
    async with db.begin():
        rows = await item_repository.list_page(
            db, tenant_id=tenant_id, is_active=is_active,
            name_prefix=name_prefix.strip() if name_prefix else None,
            after=after, limit=limit + 1,
        )
    page_rows = rows[:limit]
    items = [ItemResponse.model_validate(row) for row in page_rows]
    next_cursor = encode_cursor(page_rows[-1].name, page_rows[-1].id) if len(rows) > limit else None
    return Page[ItemResponse](items=items, next_cursor=next_cursor)