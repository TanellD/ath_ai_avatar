"""Сессия Soniox не должна простаивать в ожидании LLM.

Замерено на живом сервисе: паузы между кусками текста по 4 с — 3 успеха из 4,
по 10 с — 0 из 4, причём каждый обрыв ровно на 10.0 с. Без пауз — 4 из 4. То
есть Soniox рвёт открытую сессию примерно через десять секунд тишины, а
`texts` в synthesize_stream — это `sentences()`, темп которого задаёт LLM.

Утренняя правка убрала ожидание ДО первого предложения. Эти тесты про
ожидание МЕЖДУ предложениями: поток режется на пачки, и каждая уходит своей
сессией.
"""

import asyncio
from collections.abc import AsyncIterator

from app.tts.soniox import _idle_bounded_batches


async def feed(items: list[tuple[float, str]]) -> AsyncIterator[str]:
    """Куски текста с заданными паузами перед каждым."""
    for delay, text in items:
        if delay:
            await asyncio.sleep(delay)
        yield text


async def collect(items: list[tuple[float, str]], idle: float) -> list[list[str]]:
    return [batch async for batch in _idle_bounded_batches(feed(items), idle)]


async def test_text_without_pauses_stays_one_session() -> None:
    """Обычный случай: LLM отдаёт предложения подряд — резать нечего, и лишних
    рукопожатий быть не должно."""
    batches = await collect([(0, "Первое."), (0, " Второе."), (0, " Третье.")], idle=0.2)

    assert batches == [["Первое.", " Второе.", " Третье."]]


async def test_long_pause_closes_the_batch() -> None:
    """Пауза дольше порога — текущая сессия закрывается, следующая откроется
    уже под новый текст. Именно этот разрыв и ронял ход целиком."""
    batches = await collect([(0, "Первое."), (0.3, " Второе.")], idle=0.1)

    assert batches == [["Первое."], [" Второе."]]


async def test_chunk_arriving_during_the_cut_is_not_lost() -> None:
    """Кусок, пришедший ровно в момент нарезки, обязан попасть в следующую
    пачку: задача чтения переживает тайм-аут и дочитывается дальше."""
    batches = await collect([(0, "А."), (0.15, "Б."), (0, "В.")], idle=0.1)

    assert [c for batch in batches for c in batch] == ["А.", "Б.", "В."]


async def test_first_chunk_is_awaited_without_limit() -> None:
    """Пока первого куска нет, ни одной сессии не открыто и таймаут Soniox не
    тикает — ждать можно сколько угодно. Иначе долгий LLM резал бы реплику на
    пустые пачки ещё до её начала."""
    batches = await collect([(0.4, "Наконец-то.")], idle=0.05)

    assert batches == [["Наконец-то."]]


async def test_empty_stream_yields_nothing() -> None:
    async def nothing() -> AsyncIterator[str]:
        return
        yield  # pragma: no cover — делает функцию асинхронным генератором

    assert [b async for b in _idle_bounded_batches(nothing(), 0.1)] == []


async def test_consumer_stopping_early_cancels_the_reader() -> None:
    """Отмена хода (§6) разворачивает стек через `finally` — висящая задача
    чтения не должна пережить генератор."""
    source = feed([(0, "Первое."), (5.0, " Второе.")])
    batches = _idle_bounded_batches(source, 0.1)

    assert await anext(batches) == ["Первое."]
    await batches.aclose()

    # Ни одной задачи, ждущей текст, после закрытия не остаётся.
    alive = [t for t in asyncio.all_tasks() if "_pull_next" in repr(t.get_coro())]
    assert not alive
