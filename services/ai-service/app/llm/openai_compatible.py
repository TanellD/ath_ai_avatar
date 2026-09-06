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

import httpx
from openai import AsyncOpenAI

from app.core.logging import get_logger
from app.llm.base import LlmProvider

log = get_logger(__name__)

# Reasoning-модели (Qwen3 через Ollama и т.п.) по умолчанию генерируют
# скрытый chain-of-thought в отдельном поле `reasoning` ПЕРЕД `content` —
# наш стрим читает только `delta.content` (см. ниже), так что "думание" не
# протечёт в субтитры, но съест весь time-to-first-token бюджет (§9
# Claude.md: 300–800 мс на первый токен) и может исчерпать max_tokens раньше,
# чем модель дойдёт до самого ответа (`finish_reason: "length"` с пустым
# content). `reasoning_effort: "none"` — параметр OpenAI Chat Completions,
# который Ollama (0.32+) уважает и отключает reasoning-трейс целиком.
# На провайдерах, где это поле не поддерживается (VseLLM/gemini), лишний
# необязательный параметр в теле запроса игнорируется.
_DISABLE_REASONING: dict[str, Any] = {"reasoning_effort": "none"}


class OpenAiCompatibleProvider(LlmProvider):
    def __init__(self, api_key: str, base_url: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        # Корень сервера без "/v1" — для нативного эндпоинта Ollama ниже
        # (keep_warm). У OpenAI-совместимого /v1/chat/completions параметр
        # keep_alive молча игнорируется (проверено вручную), у Ollama он есть
        # только в её собственном /api/generate.
        self._ollama_root = base_url[: -len("/v1")] if base_url.endswith("/v1") else base_url

    @property
    def name(self) -> str:
        return "openai_compatible"

    async def aclose(self) -> None:
        await self._client.close()

    async def keep_warm(self, models: list[str], keep_alive: str = "10m") -> None:
        """Держит модели резидентными в VRAM Ollama дольше её дефолтных 5 минут.

        Не часть контракта LlmProvider — это не про генерацию ответа, а про
        конкретную особенность Ollama на общем сервере: без этого модель
        выгружается из памяти в простое между сообщениями сотрудника, и
        следующий ответ персонажа платит десятки секунд холодной загрузки
        (см. обсуждение в чате 2026-09-05 — 41с у 35B-модели против TTFT
        обычно <1с). Правка на самом сервере требует root, которого нет —
        поэтому держим тепло пингами отсюда, раз в несколько минут
        (см. main.py, keep_warm_loop).

        На не-Ollama OpenAI-совместимых прокси (VseLLM и т.п.) эндпоинта
        /api/generate нет — ошибка тихо логируется и не мешает основной
        работе провайдера.
        """
        async with httpx.AsyncClient(base_url=self._ollama_root, timeout=15.0) as client:
            for model in dict.fromkeys(models):  # dict.fromkeys — дедуп с сохранением порядка
                try:
                    response = await client.post(
                        "/api/generate",
                        json={"model": model, "prompt": "", "keep_alive": keep_alive},
                    )
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    log.warning("llm.keep_warm_failed", model=model, error=str(exc))

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
            extra_body=_DISABLE_REASONING,
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
            extra_body=_DISABLE_REASONING,
        )

        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("openai_compatible: пустой ответ модели")
        return json.loads(content)
