"""Провайдер OpenAI-совместимого API — второй вариант LLM.

Добавлен по итогам ветки `poc` изначально для VseLLM (OpenAI-совместимый
прокси) → `google/gemini-2.5-flash`. Тот же провайдер сейчас использует
фактическая рабочая конфигурация команды — собственная Ollama на удалённом
сервере, модель `qwen3.6:35b` (см. docs/PROJECT_DESCRIPTION.md, «Переход на
локальную модель», и `.env.example`). Не замена AnthropicProvider, а второй
селектируемый вариант: `LLM_PROVIDER=openai_compatible`.

Модель берётся из тех же `LLM_FAST_MODEL`/`LLM_STRONG_MODEL`, что и у
Anthropic — отдельных переменных под конкретный провайдер не заводим,
значение просто передаётся дальше как есть (сейчас это `"qwen3.6:35b"`, для
VseLLM было бы `"google/gemini-2.5-flash"`).

Structured output здесь не то же самое, что у Anthropic.
`response_format={"type": "json_object"}` — стандартный параметр Chat
Completions API, гарантирующий только синтаксически валидный JSON, а не
соответствие конкретной схеме. Поддержка этого параметра именно VseLLM не
проверялась (нет доступа к его ключу на момент написания) — поэтому схема
дополнительно вписывается в системный промпт как явная инструкция, избыточно
поверх response_format, а не вместо него.

**Почему одного `json_object` мало на локальных Qwen.** На живой сессии с
Ollama (qwen3.6:35b) `complete_json` вернул описание самой JSON Schema
(`{"type":"object","properties":...}`) вместо заполненных полей — модель
восприняла инструкцию в промпте буквально и процитировала схему, а не
следовала ей. `json_object` гарантирует только «это валидный JSON», причём
любой, а не конкретной формы. `response_format={"type": "json_schema", ...}`
(Ollama 0.5+, туда же большинство OpenAI-совместимых прокси) заставляет
сервер сузить грамматику генерации до конкретной схемы — и то же самое
воспроизведение схемы вместо ответа не повторяется. Поддержка не всюду
гарантирована (VseLLM/gemini не проверялись), поэтому при отказе сервера
принять `json_schema` (обычно `BadRequestError`/`UnprocessableEntityError`)
делаем один повторный вызов с прежним `json_object` — тем самым режимом,
что был здесь до этой правки.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import openai
from openai import AsyncOpenAI

from app.core.logging import get_logger
from app.llm.base import LlmProvider

log = get_logger(__name__)

# Ошибки, которыми провайдер обычно сигнализирует «этот response_format я не
# понимаю» — а не «модель недоступна» или «сеть моргнула». Ловим только их:
# на остальных исключениях фолбэк не нужен и только замаскировал бы реальный
# сбой (например, таймаут) вторым таким же обречённым запросом.
_UNSUPPORTED_RESPONSE_FORMAT = (openai.BadRequestError, openai.UnprocessableEntityError)


def _json_schema_response_format(schema: dict[str, Any]) -> dict[str, Any]:
    """Обёртка схемы под Chat Completions `response_format=json_schema`.

    `name` обязателен по спецификации API — берём заголовок схемы, если он
    есть, иначе нейтральное имя (модель ориентируется на само тело схемы,
    имя ей не сообщает ничего содержательного).
    """
    return {
        "type": "json_schema",
        "json_schema": {"name": schema.get("title", "response"), "schema": schema},
    }

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

# Вторая линия защиты от той же утечки. `reasoning_effort: none` — просьба к
# серверу не генерировать трейс вовсе, а не гарантия: на живой сессии модель
# всё равно написала рассуждение прямо ВНУТРИ content как
# `<thought>...</thought>`, а не в отдельном поле `reasoning` — оно ушло в
# субтитры и озвучилось сотруднику дословно, вместе с «Формулировка ответа
# Ирины: ...» и прочей служебной рефлексией персонажа. Список — известные
# варианты этого паттерна у разных открытых моделей, а не только тот, что
# видели на практике.
_REASONING_TAGS = frozenset({"think", "thinking", "thought", "reasoning"})


def _partial_suffix_match(lowered_buffer: str, needle: str) -> int:
    """Длина максимального суффикса `lowered_buffer`, совпадающего с началом
    `needle` — то есть сколько символов хвоста буфера могут оказаться
    оборванным началом ещё не долетевшего `needle` целиком.
    """
    max_len = min(len(lowered_buffer), len(needle) - 1)
    for length in range(max_len, 0, -1):
        if lowered_buffer[-length:] == needle[:length]:
            return length
    return 0


async def _strip_inline_reasoning(chunks: AsyncIterator[str]) -> AsyncIterator[str]:
    """Вырезать `<TAG>...</TAG>` (TAG из `_REASONING_TAGS`) из потока текста.

    Стриминговый, а не построчный: блок рассуждения может растянуться на
    десятки чанков, а открывающий/закрывающий тег — располовиниться между
    двумя чанками (сеть режет как придётся). Буферизуем ровно настолько,
    чтобы всегда быть уверены — очередной `<` либо точно не начало тега (уже
    видно, что после буквы не подходящее слово), либо однозначно тег, либо
    ещё нужно подождать следующий чанк.
    """
    buffer = ""
    in_tag = False
    close_tag = ""

    async for delta in chunks:
        buffer += delta
        while True:
            if not in_tag:
                start = buffer.find("<")
                if start == -1:
                    if buffer:
                        yield buffer
                        buffer = ""
                    break
                if start > 0:
                    yield buffer[:start]
                    buffer = buffer[start:]
                if len(buffer) < 2:
                    # Видели только "<" — не знаем ещё, что за ним: буква
                    # (потенциальный тег) или что угодно другое. Ждём.
                    break
                if not buffer[1].isalpha():
                    # После "<" не буква — не начало тега (например, "цена
                    # < 100"). Не ждём ">" неопределённо долго — отдаём "<"
                    # как обычный символ и разбираем остаток буфера сразу.
                    yield buffer[0]
                    buffer = buffer[1:]
                    continue
                end = buffer.find(">")
                if end == -1:
                    # Открывающий тег ещё не долетел целиком — ждём.
                    break
                tag_name = buffer[1:end].strip().lower()
                if tag_name in _REASONING_TAGS:
                    in_tag = True
                    close_tag = f"</{tag_name}>"
                    buffer = buffer[end + 1 :]
                    continue
                # Не наш тег (модель почти никогда так не пишет обычную
                # речь, но на всякий случай не теряем текст) — отдаём как
                # есть и продолжаем разбор остатка буфера.
                yield buffer[: end + 1]
                buffer = buffer[end + 1 :]
                continue

            lowered = buffer.lower()
            idx = lowered.find(close_tag)
            if idx == -1:
                # Закрывающий тег ещё не пришёл целиком — это рассуждение,
                # наружу не идёт ничего из уже накопленного. Но хвост буфера
                # может оказаться отломанным НАЧАЛОМ закрывающего тега (сеть
                # режет чанк как придётся, например "...</though" + "t>") —
                # такой хвост храним, иначе следующий чанк "t>" уже не с чем
                # склеить, и тег никогда не найдётся.
                keep = _partial_suffix_match(lowered, close_tag)
                buffer = buffer[len(buffer) - keep :] if keep else ""
                break
            buffer = buffer[idx + len(close_tag) :]
            in_tag = False
            close_tag = ""

    if in_tag:
        # Стрим оборвался внутри рассуждения — незакрытый тег означает, что
        # вся реплика персонажа молча ушла в пустоту (см. коммит,
        # добавивший эту функцию). Раньше это было видно только по тому, что
        # клиент навсегда завис на "Персонаж думает" — теперь хотя бы видно
        # в логах, что причина именно здесь, а не где-то ещё в конвейере.
        log.warning(
            "openai_compatible.unterminated_reasoning_tag",
            close_tag=close_tag,
            buffered_chars=len(buffer),
        )
    elif buffer:
        yield buffer


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
            extra_body=_DISABLE_REASONING,
        )

        async def raw_deltas() -> AsyncIterator[str]:
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta

        async for delta in _strip_inline_reasoning(raw_deltas()):
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
        response_format: dict[str, Any] = {"type": "json_object"}
        if schema is not None:
            system = (
                f"{system}\n\nОтвечай строго валидным JSON, соответствующим этой "
                "JSON Schema, без пояснений и без markdown-разметки:\n"
                f"{json.dumps(schema, ensure_ascii=False)}"
            )
            response_format = _json_schema_response_format(schema)

        full_messages = [{"role": "system", "content": system}, *messages]

        try:
            response = await self._client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=full_messages,
                response_format=response_format,
                extra_body=_DISABLE_REASONING,
            )
        except _UNSUPPORTED_RESPONSE_FORMAT as exc:
            if response_format["type"] != "json_schema":
                raise
            log.warning(
                "llm.json_schema_unsupported_fallback",
                model=model,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            response = await self._client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=full_messages,
                response_format={"type": "json_object"},
                extra_body=_DISABLE_REASONING,
            )

        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("openai_compatible: пустой ответ модели")
        return json.loads(content)
