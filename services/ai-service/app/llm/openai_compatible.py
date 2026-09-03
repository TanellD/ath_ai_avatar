"""Провайдер OpenAI-совместимого API (VseLLM/gemini) — второй вариант LLM.

Добавлен по итогам ветки `poc`: рабочий стек хакатон-команды — VseLLM
(OpenAI-совместимый прокси) → `google/gemini-2.5-flash`. Не замена
AnthropicProvider, а второй селектируемый вариант:
`LLM_PROVIDER=openai_compatible`.

Модель берётся из тех же `LLM_FAST_MODEL`/`LLM_STRONG_MODEL`, что и у
Anthropic — отдельных переменных под конкретный провайдер не заводим,
значение просто передаётся дальше как есть (для VseLLM это
`"google/gemini-2.5-flash"`).

Structured output здесь не то же самое, что у Anthropic.
`response_format={"type": "json_object"}` — стандартный параметр Chat
Completions API, гарантирующий только синтаксически валидный JSON, а не
соответствие конкретной схеме. Поддержка этого параметра именно VseLLM не
проверялась (нет доступа к его ключу на момент написания) — поэтому схема
дополнительно вписывается в системный промпт как явная инструкция, избыточно
поверх response_format, а не вместо него.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from app.core.logging import get_logger
from app.llm.base import LlmProvider

log = get_logger(__name__)


class OpenAiCompatibleProvider(LlmProvider):
    def __init__(self, api_key: str, base_url: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    @property
    def name(self) -> str:
        return "openai_compatible"

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

        Отмена: закрытие клиентского соединения при task.cancel() в gateway
        обрывает HTTP-стрим — отдельного сигнала не нужно, так же как у
        AnthropicProvider.
        """
        stream = await self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "system", "content": system}, *messages],
            stream=True,
        )

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    async def complete_json(
        self,
        system: str,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if schema is not None:
            system = (
                f"{system}\n\nОтвечай строго валидным JSON, соответствующим этой "
                "JSON Schema, без пояснений и без markdown-разметки:\n"
                f"{json.dumps(schema, ensure_ascii=False)}"
            )

        response = await self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "system", "content": system}, *messages],
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("openai_compatible: пустой ответ модели")
        return json.loads(content)
