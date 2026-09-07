"""Поколения ответа и протокол отмены — Claude.md §6.

Единственное место, где ошибка гарантированно убивает демо.

Инвариант (метрика 4): **после отмены ни один чанк старого поколения не
воспроизводится.** Ноль возвратов — не цель, а требование.

Механизм не зависит от способа ввода: триггер отмены — либо отправка текстовой
реплики, либо голосовой onset (сейчас push-to-talk, `speech_start`; полноценный
клиентский VAD-onset без удержания кнопки — открытый пункт, см.
docs/PROJECT_DESCRIPTION.md). Ниже триггера последовательность одна и та же:

    bump() -> cancel(old) -> отбрасывание по gen_id

Поэтому реализация здесь считается финальной, а не временной. См.
docs/engineering/stt-phase.md.
"""

import asyncio
from dataclasses import dataclass, field

from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class GenerationRegistry:
    """Счётчик поколений одной сессии плюс реестр задач этого поколения.

    Живёт в памяти процесса, по одному экземпляру на WebSocket-соединение.
    Именно поэтому gateway запускается одним воркером (см. Dockerfile).
    """

    _current: int = 0
    _tasks: dict[int, set[asyncio.Task[None]]] = field(default_factory=dict)

    # -------------------------------------------------------------- чтение

    @property
    def current(self) -> int:
        """gen_id актуального поколения."""
        return self._current

    def is_stale(self, gen_id: int) -> bool:
        """Проверять ПЕРЕД отправкой любого события клиенту.

        Второй рубеж защиты: клиент тоже отбрасывает события с чужим gen_id
        (§6, шаг 7), но полагаться на клиента для жёсткого инварианта нельзя.
        """
        return gen_id != self._current

    # --------------------------------------------------------------- запись

    def restore(self, gen_id: int) -> None:
        """Продолжить нумерацию после переподключения.

        Счётчик обязан идти дальше, а не начинаться заново: иначе gen_id из
        оборвавшегося соединения совпал бы с новым, и звук, уже отброшенный
        как протухший, снова прошёл бы проверку на свежесть.
        """
        self._current = max(self._current, gen_id)

    def bump(self) -> int:
        """Открыть новое поколение. Возвращает новый gen_id.

        Инкремент делается ДО отмены старых задач, чтобы между двумя
        операциями не осталось окна, в котором `is_stale` ещё разрешает
        отправку хвоста.
        """
        self._current += 1
        log.debug("generation.bump", gen_id=self._current)
        return self._current

    def register(self, gen_id: int, task: asyncio.Task[None]) -> None:
        """Привязать задачу (стрим LLM или TTS) к поколению.

        Задача снимает себя с учёта сама по завершении, иначе реестр растёт
        на всю длину сессии.
        """
        tasks = self._tasks.setdefault(gen_id, set())
        tasks.add(task)
        task.add_done_callback(lambda t: tasks.discard(t))

    async def cancel(self, gen_id: int) -> None:
        """Отменить все задачи поколения и дождаться их фактической остановки.

        Ждём именно завершения: `task.cancel()` только просит остановиться, и
        без ожидания есть окно, в котором отменённая корутина успевает
        дописать чанк в сокет. Это ровно та щель, через которую метрика 4
        превращается из нуля в единицу.
        """
        tasks = self._tasks.pop(gen_id, set())
        if not tasks:
            return

        for task in tasks:
            task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)
        log.info("generation.cancelled", gen_id=gen_id, tasks=len(tasks))

    async def cancel_all(self) -> None:
        """Закрытие соединения: снять всё, что осталось."""
        for gen_id in list(self._tasks):
            await self.cancel(gen_id)
