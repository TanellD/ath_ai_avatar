"""Движок SQLAlchemy scenario-service. См. комментарии в gateway/app/db/engine.py."""

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine() -> AsyncEngine:
    url = get_settings().database_url
    engine = create_async_engine(url, echo=False, future=True)

    if url.startswith("sqlite"):
        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record) -> None:  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


async def init_engine(create_tables: bool = True) -> None:
    global _engine, _session_factory
    _engine = create_engine()
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    if create_tables:
        # Как и в gateway: убрать, как только появится первая ревизия alembic.
        from app.db.models import Base

        async with _engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_session() -> AsyncIterator[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("engine is not initialised; init_engine() must run in lifespan")
    async with _session_factory() as session:
        yield session


def session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("engine is not initialised; init_engine() must run in lifespan")
    return _session_factory
