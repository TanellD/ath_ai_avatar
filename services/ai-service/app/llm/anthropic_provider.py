"""Провайдер Anthropic Claude.

Разделение моделей (Claude.md §5) отображается сюда так:

  - реплики персонажа — `claude-haiku-4-5`. Приоритет — время до первого токена;
    thinking не включаем: он тратит бюджет метрики 1, а глубоких рассуждений в
    реплике закупщика не требуется;
  - итоговая оценка — `claude-opus-5`, один вызов, structured output.
    Здесь наоборот: думать модель должна, а скорость не важна вообще.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from app.core.logging import get_logger
from app.llm.base import LlmProvider

log = get_logger(__name__)

_NO_SAMPLING_PREFIXES = ("claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-5")
"""Модели, где temperature/top_p убраны из API и возвращают 400.

Проверка нужна не ради красоты: LLM_FAST_MODEL задаётся переменной окружения,
и если кто-то поставит туда opus, сервис должен продолжить работать, а не
падать на каждой реплике.
"""


def _supports_sampling(model: str) -> bool:
    return not model.startswith(_NO_SAMPLING_PREFIXES)


class AnthropicProvider(LlmProvider):
    def __init__(self, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    @property
    def name(self) -> str:
        return "anthropic"

    async def aclose(self) -> None:
        await self._client.close()

    async def stream(
        self,
        system: str,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[str]:
        """Поток текста реплики персонажа.

        Отмена: при `task.cancel()` в gateway соединение закрывается выходом из
        `async with`, и генерация на стороне API прекращается. Отдельного
        сигнала отмены не нужно.
        """
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if _supports_sampling(model):
            kwargs["temperature"] = temperature

        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text

    async def complete_json(
        self,
        system: str,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Один вызов со структурированным ответом.

        Схема передаётся в `output_config.format`, а не «просим в промпте
        отдать JSON»: отчёт — единственный артефакт, который видит методист, и
        разбирать его регулярками, как это делает референсный проект, значит
        периодически показывать методисту пустой отчёт.
        """
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if _supports_sampling(model):
            kwargs["temperature"] = temperature
        if schema is not None:
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": schema}}

        response = await self._client.messages.create(**kwargs)

        if response.stop_reason == "refusal":
            raise RuntimeError(f"модель отказалась отвечать: {response.stop_details}")

        text = next(block.text for block in response.content if block.type == "text")
        return json.loads(text)
