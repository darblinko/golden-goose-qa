"""SQLAlchemy engine/session factories. One engine per process, injected settings."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from gg_common.settings import PostgresSettings


def create_engine(settings: PostgresSettings, *, pool_size: int = 5) -> AsyncEngine:
    return create_async_engine(
        settings.sqlalchemy_url,
        pool_size=pool_size,
        max_overflow=5,
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
