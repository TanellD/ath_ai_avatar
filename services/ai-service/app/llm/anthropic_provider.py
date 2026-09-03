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
"""Модели, которые отвечают 400 на любой запрос, несущий temperature (даже
дефолтное значение) — Opus 4.7+ безусловно, Sonnet 5 на не-дефолтных значениях;
здесь исключены оба класса целиком, консервативно.

Важно не путать это с версией SDK: в anthropic>=1.0 (сейчас используется)
`temperature`/`top_p`/`top_k` вообще убраны из сигнатур `messages.create()` и
`messages.stream()` — они передаются через `extra_body`, а не именованным
аргументом, независимо от того, что тут ниже. Этот список — про то, готова ли
МОДЕЛЬ принять параметр; `extra_body` — про то, как его теперь физически
передать через SDK. Проверка нужна не ради красоты: LLM_FAST_MODEL задаётся
переменной окружения, и если кто-то поставит туда opus, сервис должен
продолжить работать, а не падать на каждой реплике.
"""


def _supports_sampling(model: str) -> bool:
    return not model.startswith(_NO_SAMPLING_PREFIXES)


def _strip_code_fence(text: str) -> str:
    """Снять обёртку ```json ... ``` / ``` ... ```, если модель её добавила.

    Не regex-экстракция JSON из прозы (от такого подхода мы сознательно
    отказались — см. докстринг complete_json). Узкая, детерминированная
    отмена ровно одного конкретного формата: даже с прямой инструкцией «без
    markdown-разметки» модель через один сторонний шлюз всё равно завернула
    валидный JSON в код-блок. Строка, не начинающаяся и не заканчивающаяся
    тройными бэктиками, возвращается как есть — json.loads() ниже упадёт со
    своей обычной понятной ошибкой, а не будет тихо изменена под что-то
    похожее на успех.
    """
    stripped = text.strip()
    if not stripped.startswith("```") or not stripped.endswith("```"):
        return text
    lines = stripped.split("\n")
    if len(lines) < 2:
        return text
    return "\n".join(lines[1:-1])


class AnthropicProvider(LlmProvider):
    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        # base_url=None (не "") — SDK трактует None как «использовать
        # api.anthropic.com по умолчанию»; пустая строка была бы невалидным URL.
        self._client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url or None)

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
            # anthropic>=1.0: temperature больше не именованный параметр
            # messages.create()/.stream() — TypeError, если передать его так.
            # extra_body мержится в тело запроса как есть, в обход сигнатуры.
            kwargs["extra_body"] = {"temperature": temperature}

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

        Схема передаётся в `output_config.format` — на настоящем
        api.anthropic.com этого достаточно, формат гарантирован сервером.

        Но `AnthropicProvider` теперь может работать и через сторонний шлюз
        (ANTHROPIC_BASE_URL, см. §10) — а шлюз не обязан поддерживать
        `output_config` так же полно. Проверено вживую на одном таком шлюзе:
        `output_config.format` был молча проигнорирован, и модель просто
        написала обычный текст ответа со свободной формулировкой классификации
        внутри прозы вместо JSON. Поэтому схема ДОПОЛНИТЕЛЬНО вписывается в
        системный промпт как явная инструкция — избыточно поверх
        output_config на настоящем API, но именно она вытягивает результат
        там, где output_config молча не сработал. Если и это не поможет —
        json.loads ниже упадёт громко, а не тихо вернёт мусор: разбирать
        ответ регулярками, как это делает референсный проект
        (`extractJsonWithoutRegex`), означает периодически показывать
        методисту пустой отчёт, и мы так не делаем.
        """
        if schema is not None:
            system = (
                f"{system}\n\nОтвечай строго валидным JSON, соответствующим этой "
                "JSON Schema, без пояснений и без markdown-разметки:\n"
                f"{json.dumps(schema, ensure_ascii=False)}"
            )

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if _supports_sampling(model):
            # anthropic>=1.0: temperature больше не именованный параметр
            # messages.create()/.stream() — TypeError, если передать его так.
            # extra_body мержится в тело запроса как есть, в обход сигнатуры.
            kwargs["extra_body"] = {"temperature": temperature}
        if schema is not None:
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": schema}}

        response = await self._client.messages.create(**kwargs)

        if response.stop_reason == "refusal":
            raise RuntimeError(f"модель отказалась отвечать: {response.stop_details}")

        text = next(block.text for block in response.content if block.type == "text")
        try:
            return json.loads(_strip_code_fence(text))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"модель вернула не-JSON ответ (шлюз мог проигнорировать "
                f"output_config.format): {text[:300]!r}"
            ) from exc
