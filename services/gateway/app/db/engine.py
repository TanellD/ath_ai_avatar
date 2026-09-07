"""Движок SQLAlchemy.

SQLite через aiosqlite. Переезд на Postgres — смена DATABASE_URL и ничего
больше: модели и репозитории общие, диалект-специфичных вызовов в коде нет.
Единственная особенность SQLite обёрнута здесь (см. _sqlite_pragmas).
"""

from collections.abc import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

#: Сколько ждать освобождения записи, прежде чем признать БД занятой.
#: Выбран с запасом над наблюдавшимся окном в 16 с — лучше медленный ответ,
#: чем 500 на ровном месте.
SQLITE_BUSY_TIMEOUT_MS = 30_000

#: Отдельное, короткое ожидание для пробы готовности. Рабочая запись и зонд
#: мониторинга хотят противоположного: сессию сотрудника стоит подождать
#: тридцать секунд, а /ready обязан ответить быстро. С общим таймаутом проба
#: висела ровно 30 с и для зонда с пятисекундным лимитом выглядела зависанием,
#: а не красным статусом — то есть одна ложь («всё хорошо») сменилась бы другой.
READINESS_BUSY_TIMEOUT_MS = 2_000

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
            """WAL, внешние ключи и ожидание блокировки.

            WAL нужен, чтобы запись хода не блокировала чтение отчёта: без
            него SQLite сериализует их и параллельная сессия методиста
            упирается в «database is locked».

            busy_timeout задаём ЯВНО. Умолчание драйвера — 5 с, и этого не
            хватает: замер показал окно занятой записи в 16 с (чекпойнт WAL
            на медленном томе), в которое POST /sessions попадал и отдавал
            500 вместо того, чтобы дождаться. Писатель, которому осталось
            подождать, обязан ждать, а не падать: пользователь видит разницу
            как «сервис не работает» против «сессия открылась чуть позже».
            """
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
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


async def check_writable() -> None:
    """Проверить, что БД доступна НА ЗАПИСЬ. Бросает, если нет.

    Обычная проба `SELECT 1` этого не показывает: в WAL чтение продолжает
    работать, когда запись уже заблокирована наглухо. Ровно так и вышло —
    /ready рапортовал `database: ok`, а каждый POST /sessions падал с
    «database is locked»: готовность была зелёной у сервиса, который не мог
    завести ни одной сессии.

    `BEGIN IMMEDIATE` берёт ту самую блокировку записи, за которую идёт борьба,
    и тут же отпускает — данные не меняются. Нужен AUTOCOMMIT: иначе SQLAlchemy
    откроет свою транзакцию и SQLite ответит «transaction within a transaction».
    """
    if _engine is None:
        raise RuntimeError("engine is not initialised; init_engine() must run in lifespan")

    async with _engine.connect() as connection:
        if not _is_sqlite(get_settings().database_url):
            # У Postgres нет глобальной блокировки записи, отдельная проба не
            # нужна: там связь либо есть, либо нет.
            await connection.execute(text("SELECT 1"))
            return
        raw = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await raw.execute(text(f"PRAGMA busy_timeout={READINESS_BUSY_TIMEOUT_MS}"))
        try:
            await raw.execute(text("BEGIN IMMEDIATE"))
            await raw.execute(text("ROLLBACK"))
        finally:
            # Подключение уходит обратно в пул и будет обслуживать обычные
            # запросы — вернуть ему рабочее терпение обязательно.
            await raw.execute(text(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}"))


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
