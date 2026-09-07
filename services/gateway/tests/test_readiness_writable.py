"""Готовность обязана проверять запись, а не чтение.

Живой случай, ради которого тест и написан: файл БД на bind-mount оказался
недоступен контейнеру на запись, каждый POST /sessions падал с «database is
locked» — а /ready отвечал `database: ok`, потому что проверял `SELECT 1`.
В WAL чтение переживает заблокированную запись, поэтому читающая проба зелена
ровно тогда, когда сервис уже не может завести ни одной сессии.
"""

import sqlite3
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.db import engine as engine_module


@pytest.fixture
async def file_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Path]:
    """Настоящий файл, а не :memory:. Блокировка записи — свойство файла:
    у in-memory базы отнять её не у кого, и проверять было бы нечего."""
    path = tmp_path / "gateway.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    engine_module.get_settings.cache_clear()
    await engine_module.init_engine()
    yield path
    await engine_module.dispose_engine()
    engine_module.get_settings.cache_clear()


async def test_writable_database_passes(file_db: Path) -> None:
    await engine_module.check_writable()


async def test_locked_database_fails_readiness(file_db: Path) -> None:
    """Пока сторонний писатель держит блокировку, проба обязана упасть."""
    holder = sqlite3.connect(file_db, timeout=0.1, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(OperationalError, match="locked"):
            await engine_module.check_writable()
    finally:
        holder.execute("ROLLBACK")
        holder.close()


async def test_probe_fails_fast_and_restores_working_timeout(file_db: Path) -> None:
    """Проба обязана ответить быстро и не испортить подключение.

    Зонд мониторинга живёт с таймаутом в несколько секунд: проба, честно
    ждущая рабочие 30 с, для него неотличима от зависания. И наоборот —
    подключение уходит обратно в пул обслуживать обычные запросы, поэтому
    короткое терпение не имеет права на нём остаться.
    """
    holder = sqlite3.connect(file_db, timeout=0.1, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        started = time.monotonic()
        with pytest.raises(OperationalError, match="locked"):
            await engine_module.check_writable()
        elapsed = time.monotonic() - started
    finally:
        holder.execute("ROLLBACK")
        holder.close()

    assert elapsed < engine_module.SQLITE_BUSY_TIMEOUT_MS / 1000, (
        f"проба ждала {elapsed:.1f} с — столько же, сколько рабочая запись"
    )

    async with engine_module.session_factory()() as db:
        value = (await db.execute(text("PRAGMA busy_timeout"))).scalar_one()
    assert value == engine_module.SQLITE_BUSY_TIMEOUT_MS


async def test_reading_probe_would_have_passed(file_db: Path) -> None:
    """Контрольный: та самая `SELECT 1`, что была раньше, блокировку не видит.

    Без этого теста легко решить, что предыдущая проба «просто чуть хуже».
    Она не хуже — она зелёная в точности в аварийной ситуации.
    """
    holder = sqlite3.connect(file_db, timeout=0.1, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        async with engine_module.session_factory()() as db:
            assert (await db.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        holder.execute("ROLLBACK")
        holder.close()
