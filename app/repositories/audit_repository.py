from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def insert_entry(
    db: AsyncSession, *, tenant_id: UUID, user_id: UUID | None, entity_type: str,
    entity_id: UUID, action: str, old_values: dict | None, new_values: dict | None,
    ip_address, user_agent: str | None,
) -> None:
    """Append-only insert. There is deliberately no update or delete function."""
    await db.execute(
        insert(AuditLog).values(
            tenant_id=tenant_id, user_id=user_id, entity_type=entity_type,
            entity_id=entity_id, action=action, old_values=old_values,
            new_values=new_values, ip_address=ip_address, user_agent=user_agent,
        )
    )


async def count_failed_logins_since_last_success(
    db: AsyncSession, *, tenant_id: UUID, user_id: UUID, window_start: datetime,
) -> int:
    """
    Failed logins for one user inside the window, counting only those after
    the user's most recent successful login (a good login resets the counter).
    Served by idx_audit_logs_entity_id_type_created.
    """
    last_success = (
        select(func.max(AuditLog.created_at))
        .where(
            AuditLog.tenant_id == tenant_id, AuditLog.entity_type == "user",
            AuditLog.entity_id == user_id, AuditLog.action == "login",
        )
        .scalar_subquery()
    )
    result = await db.execute(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.tenant_id == tenant_id, AuditLog.entity_type == "user",
            AuditLog.entity_id == user_id, AuditLog.action == "login_failed",
            AuditLog.created_at >= window_start,
            or_(last_success.is_(None), AuditLog.created_at > last_success),
        )
    )
    return result.scalar_one()