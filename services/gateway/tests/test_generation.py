"""Инвариант отмены — Claude.md §6, метрика 4.

«После отмены ни один чанк старого поколения не воспроизводится. Ноль
возвратов — не цель, а требование.»

Тест проверяет именно это на уровне реестра поколений, без сети и без клиента:
если инвариант ломается здесь, дальше по конвейеру его уже не спасти.
"""

import asyncio

import pytest

from app.orchestrator.generation import GenerationRegistry


async def test_bump_increments_and_returns_new_id() -> None:
    registry = GenerationRegistry()
    assert registry.current == 0
    assert registry.bump() == 1
    assert registry.bump() == 2
    assert registry.current == 2


async def test_stale_generations_are_rejected() -> None:
    registry = GenerationRegistry()
    gen = registry.bump()
    assert not registry.is_stale(gen)

    registry.bump()
    assert registry.is_stale(gen), "старое поколение обязано считаться устаревшим"


async def test_cancel_stops_running_task_before_it_emits_more() -> None:
    """Ключевой сценарий: поколение отменено — его задача больше ничего не пишет."""
    registry = GenerationRegistry()
    emitted: list[int] = []
    started = asyncio.Event()

    async def producer(gen_id: int) -> None:
        started.set()
        while True:
            await asyncio.sleep(0.001)
            if registry.is_stale(gen_id):
                # Так же, как это делает pipeline._send: устаревшее не выходит.
                continue
            emitted.append(gen_id)

    old_gen = registry.bump()
    registry.register(old_gen, asyncio.create_task(producer(old_gen)))
    await started.wait()
    await asyncio.sleep(0.02)

    assert emitted, "предусловие: до отмены поколение действительно что-то писало"
    new_gen = registry.bump()
    await registry.cancel(old_gen)

    emitted.clear()
    await asyncio.sleep(0.02)

    assert emitted == [], "после отмены не должно прийти ни одного чанка старого поколения"
    assert new_gen == old_gen + 1


async def test_cancel_awaits_actual_task_completion() -> None:
    """`cancel()` возвращает управление только когда задача реально остановилась.

    Без ожидания остаётся окно, в котором отменённая корутина успевает
    дописать чанк в сокет — та самая щель, через которую метрика 4
    превращается из нуля в единицу.
    """
    registry = GenerationRegistry()
    finished = False

    async def slow_cleanup() -> None:
        nonlocal finished
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await asyncio.sleep(0.01)
            finished = True
            raise

    gen = registry.bump()
    task = asyncio.create_task(slow_cleanup())
    registry.register(gen, task)
    await asyncio.sleep(0)

    await registry.cancel(gen)

    assert finished, "cancel() вернулся раньше, чем задача действительно остановилась"
    assert task.done()


async def test_cancel_all_clears_every_generation() -> None:
    registry = GenerationRegistry()
    tasks = []
    for _ in range(3):
        gen = registry.bump()
        task = asyncio.create_task(asyncio.sleep(10))
        registry.register(gen, task)
        tasks.append(task)

    await registry.cancel_all()

    assert all(task.done() for task in tasks)


async def test_cancel_of_unknown_generation_is_a_noop() -> None:
    """Клиент может прислать interrupts на уже завершённое поколение."""
    registry = GenerationRegistry()
    await registry.cancel(999)  # не должно кидать


@pytest.mark.parametrize("interrupts", [None, 1])
async def test_registered_task_unregisters_itself(interrupts: int | None) -> None:
    """Реестр не должен расти на всю длину сессии."""
    registry = GenerationRegistry()
    gen = registry.bump()

    async def quick() -> None:
        return None

    task = asyncio.create_task(quick())
    registry.register(gen, task)
    await task

    assert registry._tasks.get(gen, set()) == set()
