"""Интерфейс языковой модели.

Два метода, потому что у сервиса два принципиально разных режима работы
(Claude.md §5):

  - `stream()` — реплика персонажа. Важна только скорость первого токена;
  - `complete_json()` — итоговая оценка. Один вызов, структурированный ответ,
    скорость не важна вообще.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class LlmProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def stream(
        self,
        system: str,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[str]:
        """Поток токенов. Должен отдавать первый токен как можно раньше."""
        raise NotImplementedError

    @abstractmethod
    async def complete_json(
        self,
        system: str,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Один вызов со структурированным JSON-ответом.

        Реализация обязана вернуть распарсенный dict либо кинуть исключение —
        отдавать наружу сырой текст и разбирать его у вызывающего нельзя.
        Референсный проект так и делает (`extractJsonWithoutRegex` +
        рукописный фолбэк), и это ровно то место, где отчёт молча вырождается
        в пустой.
        """
        raise NotImplementedError

    async def aclose(self) -> None:
        """Закрыть соединения провайдера.

        Не abstractmethod намеренно: у провайдера может не быть ничего, что
        нужно закрывать, и заставлять каждого писать пустую реализацию незачем.
        """
        return
