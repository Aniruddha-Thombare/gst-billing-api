from __future__ import annotations

import enum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_json import to_jsonable
from app.core.request_context import get_request_context
from app.repositories import audit_repository


def _plain(value: str | enum.Enum) -> str:
    return value.value if isinstance(value, enum.Enum) else value


async def record(
    db: AsyncSession, *, tenant_id: UUID, user_id: UUID | None,
    entity_type: str | enum.Enum, entity_id: UUID, action: str | enum.Enum,
    old_values: dict | None = None, new_values: dict | None = None,
) -> None:
    """
    Writes one audit row INSIDE the caller's open transaction, so the row
    commits or rolls back together with the mutation it describes.
    Calling it outside a transaction is a bug and fails loudly.
    """
    if not db.in_transaction():
        raise RuntimeError("audit_service.record must be called inside an open transaction")

    context = get_request_context()
    await audit_repository.insert_entry(
        db, tenant_id=tenant_id, user_id=user_id,
        entity_type=_plain(entity_type), entity_id=entity_id, action=_plain(action),
        old_values=to_jsonable(old_values) if old_values is not None else None,
        new_values=to_jsonable(new_values) if new_values is not None else None,
        ip_address=context.ip_address, user_agent=context.user_agent,
    )