from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Async Engine(connection pool)

engine = create_async_engine(
    settings.DATABASE_URL,

    # prints every SQL query directly to the terminal if we are in development mode
    echo = settings.ENVIRONMENT == "development",
    
    # Verify whether the connection is alive before handing it to the application
    pool_pre_ping = True,

    # Keeps 20 connections open and ready for instant use
    pool_size = 20,

    # Allows up to 10 extra temporary connections during traffic spikes
    max_overflow =10,

    # Waits up to 30 seconds for a connection if the pool is currently full
    pool_timeout = 30,

    # Recycles connections every 30 minutes to prevent cloud firewalls from dropping them
    pool_recycle = 1800,
)

# session factory 
SessionLocal = async_sessionmaker(
    bind = engine,
    class_ = AsyncSession,

    # Keeps ORM objects accessible in memory even after the transaction commits
    expire_on_commit = False,

    # We strictly control transactions; no auto-committing or auto-flushing
    autocommit=False,
    autoflush=False,
)

# Base Model (For ORM Models)
class Base(DeclarativeBase):
    pass

# Database Dependency (Fastapi)
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency. Injected into every endpoint that needs DB access.
    Yields a database session.
    Transaction management (commit/rollback) is handled explicitly 
    by the service layer using `async with db.begin():`
    """
    async with SessionLocal() as session:
        yield session
