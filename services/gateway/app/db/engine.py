"""Движок SQLAlchemy.

SQLite через aiosqlite. Переезд на Postgres — смена DATABASE_URL и ничего
больше: модели и репозитории общие, диалект-специфичных вызовов в коде нет.
Единственная особенность SQLite обёрнута здесь (см. _sqlite_pragmas).
"""

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


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def create_engine() -> AsyncEngine:
    settings = get_settings()
    url = settings.database_url

    engine = create_async_engine(url, echo=False, future=True)

    if _is_sqlite(url):
        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record) -> None:  # noqa: ANN001
            """WAL и внешние ключи.

            WAL нужен, чтобы запись хода не блокировала чтение отчёта: без
            него SQLite сериализует их и параллельная сессия методиста
            упирается в «database is locked».
            """
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    return engine


async def init_engine(create_tables: bool = True) -> None:
    global _engine, _session_factory
    _engine = create_engine()
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    if create_tables:
        # Скелету нужно, чтобы `docker compose up` поднимался на чистом клоне
        # без ручного шага миграции. Как только появится первая ревизия
        # alembic, это надо убрать: два способа создавать схему неизбежно
        # разъедутся. См. app/alembic/README.md.
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
    """Зависимость FastAPI: одна сессия на запрос."""
    if _session_factory is None:
        raise RuntimeError("engine is not initialised; init_engine() must run in lifespan")
    async with _session_factory() as session:
        yield session


def session_factory() -> async_sessionmaker[AsyncSession]:
    """Для кода вне HTTP-запроса (WebSocket-обработчик, фоновые задачи)."""
    if _session_factory is None:
        raise RuntimeError("engine is not initialised; init_engine() must run in lifespan")
    return _session_factory
