from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator
from app.config import settings

# Async Engine(connection pool)

engine = create_async_engine(
    settings.database_url,
    echo = settings.environment == "development",
    pool_pre_ping = True,
    pool_size = 5,
    max_overflow =10,
    pool_timeout = 30,
    pool_recycle = 1800,
)

# session factory 
SessionLocal = async_sessionmaker(
    bind = engine,
    class_ = AsyncSession,
    expire_on_commit = False,
)

# Base Model (For ORM Models)
class Base(DeclarativeBase):
    pass

# Database Dependency (Fastapi)
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
