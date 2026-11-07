from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# The scheduler is its own process, so it gets its own small engine.
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=2,
    max_overflow=1,
    pool_pre_ping=True,
    connect_args={"server_settings": {
        "application_name": "gst_scheduler",
        "statement_timeout": "300000",              # 5 min: batch jobs, not requests
        "idle_in_transaction_session_timeout": "60000",
    }},
)

SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)