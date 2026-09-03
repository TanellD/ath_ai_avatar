"""Интерфейс потокового распознавания — Claude.md §5, §10.

**Определение, не реализация.** Голосовой ввод — следующая фаза; сейчас
пользователь печатает. Ничто в проекте этот модуль не импортирует.

Форма интерфейса зафиксирована заранее по трём причинам, каждая из которых
влияет на код за пределами этого файла:

1. **Партиалы обязательны, а не опциональны.** Из них живут субтитры до
   финализации и спекулятивный prefill LLM — единственный способ удержать
   цель метрики 1 (≤1.5 с), когда в бюджет добавились VAD endpoint (200-500 мс)
   и финализация STT (100-300 мс).
2. **`confidence` возвращается всегда.** Под цитатой в отчёте низкая
   уверенность рисуется флагом «перепроверь на слух» (§7). Провайдер,
   не отдающий уверенность, ломает интерфейс методиста, а не только логи.
3. **Тайминги слов нужны для `audio_ref`.** Чтобы методист слушал ровно ту
   фразу, а не всю запись, надо знать её границы в исходном аудио.

Критерий выбора провайдера — качество на числах, ценах и названиях: ошибки STT
попадают прямо в `evidence`, а `evidence` и есть главная гипотеза продукта.
Кандидаты (проверить актуальные языки/латентность/цены перед выбором):

  - **Deepgram** — низкая латентность финализации, хорошее потоковое API;
  - **Yandex SpeechKit** — нативный русский, локальный регион;
  - **Google STT** — запасной вариант.

Локальный инференс вне скоупа (§4). VAD здесь тоже быть не должно — он живёт
на клиенте ради barge-in <300 мс.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptUpdate:
    """Партиал или финал распознавания одной реплики."""

    text: str
    is_final: bool
    confidence: float
    """0.0-1.0. Провайдер, не дающий уверенность, обязан вернуть 1.0 для
    финала и 0.0 для партиала — молча подставлять None нельзя, иначе флаг
    «перепроверь на слух» в отчёте не сработает."""

    start_ms: int | None = None
    end_ms: int | None = None
    """Границы фразы в исходном аудио — из них строится AudioRef (§7)."""


class SttProvider(ABC):
    """Потоковое распознавание речи по API.

    Жизненный цикл одной реплики:

        provider.open()                     # соединение с провайдером
        for chunk in audio: provider.push(chunk)
        provider.finalize()                 # по VAD endpoint от клиента
        async for update in provider.updates(): ...
        provider.aclose()

    Реализация обязана быть отменяемой: при перебивании gateway снимает
    задачу, и провайдер должен закрыть соединение по CancelledError.
    """

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def open(self, sample_rate: int, language: str = "ru") -> None:
        """Открыть сессию распознавания."""
        raise NotImplementedError

    @abstractmethod
    async def push(self, audio: bytes) -> None:
        """Отправить чанк аудио. Порядок чанков — ответственность вызывающего."""
        raise NotImplementedError

    @abstractmethod
    async def finalize(self) -> None:
        """Сигнал конца реплики (VAD endpoint на клиенте).

        Провайдер должен выдать финальный транскрипт за 100-300 мс — это его
        доля в бюджете метрики 1 (§9).
        """
        raise NotImplementedError

    @abstractmethod
    def updates(self) -> AsyncIterator[TranscriptUpdate]:
        """Поток партиалов и финала."""
        raise NotImplementedError

    @abstractmethod
    async def aclose(self) -> None:
        """Закрыть сессию и освободить соединение."""
        raise NotImplementedError
