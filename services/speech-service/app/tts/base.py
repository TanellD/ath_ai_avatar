"""Интерфейс потокового синтеза — Claude.md §3, §10.

Требование: «TTS озвучивает ответ по частям, пользователь не ждёт генерации
целиком». Поэтому интерфейс — асинхронный генератор чанков, а не функция,
возвращающая готовый файл. Провайдер, умеющий отдать только целиком, обязан
сам нарезать результат, но не притворяться потоковым в бюджете метрики 1.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

from ath_contracts import Mood


@dataclass(frozen=True)
class AudioChunk:
    """Кусок синтезированного аудио."""

    data: bytes
    sample_rate: int
    is_final: bool = False


class TtsProvider(ABC):
    """Базовый провайдер синтеза.

    Реализация обязана быть отменяемой: gateway снимает задачу при
    перебивании (§6), и провайдер должен корректно закрыть соединение по
    `asyncio.CancelledError`, а не продолжать качать аудио в никуда.
    """

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def synthesize(
        self, text: str, voice_id: str | None = None, mood: Mood = Mood.NEUTRAL
    ) -> AsyncIterator[AudioChunk]:
        """Синтезировать текст, отдавая чанки по мере готовности.

        Первый чанк — самое важное число этого сервиса: на TTS в бюджете
        ответа отведено 150-400 мс до первого чанка (§9).
        """
        ...

    async def aclose(self) -> None:
        """Закрыть соединения провайдера.

        Не abstractmethod намеренно: у провайдера может не быть ничего, что
        нужно закрывать, и заставлять каждого писать пустую реализацию незачем.
        """
        return
