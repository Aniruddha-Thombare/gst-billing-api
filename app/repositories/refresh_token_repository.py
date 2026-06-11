from uuid import UUID
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken
from app.core.security import hash_refresh_token
from app.config import settings


async def create(
    db: AsyncSession,
    *,
    user_id: UUID,
    tenant_id: UUID,
    raw_token: str,     # the actual token string (from create_refresh_token())
    device_info: str | None = None,
) -> RefreshToken:
    """
    Stores a new refresh token (as its SHA-256 hash).
    
    NEVER call this with an already-hashed token.
    Hashing happens inside this function. This is the one place
    where raw → hashed conversion occurs.
    """
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    # The expiry is stored in DB independent of the JWT exp claim.
    # This allows DB-side cleanup of expired tokens even if the JWT
    # was somehow issued with a wrong expiry.

    token = RefreshToken(
        user_id=user_id,
        tenant_id=tenant_id,
        token_hash=hash_refresh_token(raw_token),   # store only the hash
        expires_at=expires_at,
        device_info=device_info,
    )
    db.add(token)
    await db.flush()
    return token


async def get_by_raw_token(db: AsyncSession, *, raw_token: str, tenant_id: UUID) -> RefreshToken | None:
    """
    Look up a RefreshToken row by the raw token string.
    
    Hashes the raw token first, then queries by hash.
    This is the verification step — we cannot look up by raw token
    because raw tokens are never stored.
    """
    token_hash = hash_refresh_token(raw_token)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.tenant_id == tenant_id,
            RefreshToken.token_hash == token_hash,
            )
    )
    return result.scalar_one_or_none()


async def revoke(db: AsyncSession, *, raw_token: str, tenant_id:UUID) -> None:
    """
    Mark a specific refresh token as revoked.
    Called on: POST /auth/logout
    
    Sets revoked_at to now. The token remains in the DB (for audit trail)
    but is_valid will return False.
    """
    token_hash = hash_refresh_token(raw_token)
    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.tenant_id == tenant_id
        )
        .values(revoked_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    )


async def revoke_all_for_user(db: AsyncSession, *, user_id: UUID, tenant_id:UUID) -> None:
    """
    Revoke ALL active refresh tokens for a user.
    
    Called when:
      - User changes their password
      - Admin deactivates a user account
      - Security incident — "log me out everywhere"
    
    This is the nuclear option — all sessions terminated.
    """
    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.tenant_id == tenant_id,
            RefreshToken.revoked_at.is_(None),     # only revoke active tokens

        )
        .values(revoked_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    )


async def delete_expired(db: AsyncSession) -> int:
    """
    Hard-delete expired refresh tokens from the DB.
    
    Called by a background job (celery beat / APScheduler) on a schedule.
    Without this, the table grows forever (one row per login).
    
    Returns the number of rows deleted (for logging).
    """
    result = await db.execute(
        delete(RefreshToken)
        .where(RefreshToken.expires_at < datetime.now(timezone.utc))
    )
    return result.rowcount or 0 