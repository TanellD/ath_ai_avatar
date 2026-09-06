"""Писатель обязан ДОЖДАТЬСЯ занятой записи, а не отдать 500.

Живой случай: окно занятой записи длилось 16 секунд, а busy_timeout стоял
драйверный по умолчанию — 5 секунд. POST /sessions, попавший в это окно,
падал с «database is locked», хотя ему оставалось только подождать.
"""

import asyncio
import sqlite3
import threading
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db import engine as engine_module


@pytest.fixture
async def file_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Path]:
    path = tmp_path / "gateway.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    engine_module.get_settings.cache_clear()
    await engine_module.init_engine()
    yield path
    await engine_module.dispose_engine()
    engine_module.get_settings.cache_clear()


async def test_busy_timeout_is_set_explicitly(file_db: Path) -> None:
    """Умолчание драйвера (5000) означало бы, что прагму забыли."""
    async with engine_module.session_factory()() as db:
        value = (await db.execute(text("PRAGMA busy_timeout"))).scalar_one()
    assert value == engine_module.SQLITE_BUSY_TIMEOUT_MS


async def test_writer_waits_out_a_busy_window(file_db: Path) -> None:
    """Чужая запись держится дольше, чем длится «мгновенная» попытка, —
    и всё равно наш писатель проходит, потому что ждёт."""
    released = threading.Event()

    def hold() -> None:
        holder = sqlite3.connect(file_db, timeout=1, isolation_level=None)
        holder.execute("BEGIN IMMEDIATE")
        released.wait(2.0)
        holder.execute("ROLLBACK")
        holder.close()

    worker = threading.Thread(target=hold)
    worker.start()
    try:
        await asyncio.sleep(0.3)  # блокировка уже взята
        task = asyncio.create_task(engine_module.check_writable())
        await asyncio.sleep(0.5)
        assert not task.done(), "проба не стала ждать — busy_timeout не действует"
        released.set()
        await task  # дождался и прошёл, а не упал
    finally:
        released.set()
        worker.join(timeout=5)
