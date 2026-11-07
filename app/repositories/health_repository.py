"""Health repository — the only DB access the readiness probe needs."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def ping_database(db: AsyncSession) -> None:
    """Round-trip to Postgres. Raises if the database cannot answer."""
    await db.execute(text("SELECT 1"))
