"""Доставка схемы в OpenAI-совместимый провайдер.

Живой сбой, ради которого всё сделано: локальная Qwen через Ollama вернула
ОПИСАНИЕ самой JSON Schema (`{"type":"object","properties":...}`) вместо
заполненных полей. `json_object` гарантирует лишь «это валидный JSON» — любой
формы, — а схема лежала ещё и в системном промпте, и модель процитировала её
буквально. `json_schema` сужает грамматику генерации на стороне сервера.

Поддержка есть не везде (VseLLM и gemini не проверялись), поэтому при отказе
сервера принять формат делается один повтор в прежнем режиме. Ветка пришла без
тестов на оба пути — здесь ровно они.
"""

import json
from typing import Any

import httpx
import openai
import pytest

from app.llm.openai_compatible import OpenAiCompatibleProvider

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"verdict": {"type": "string"}},
    "required": ["verdict"],
    "additionalProperties": False,
}

ANSWER = json.dumps({"verdict": "готово"}, ensure_ascii=False)


def provider_over(handler) -> OpenAiCompatibleProvider:  # noqa: ANN001
    """Настоящий клиент SDK поверх подставного транспорта: так проверяется
    ровно то, что уходит на провод, а не наши представления о нём."""
    instance = OpenAiCompatibleProvider(api_key="test", base_url="http://llm/v1")
    instance._client = openai.AsyncOpenAI(
        api_key="test",
        base_url="http://llm/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return instance


def chat_completion(content: str) -> dict[str, Any]:
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": "qwen",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


async def complete(instance: OpenAiCompatibleProvider, schema: dict | None = SCHEMA) -> dict:
    return await instance.complete_json(
        system="s", messages=[{"role": "user", "content": "u"}],
        model="qwen", max_tokens=100, temperature=0.0, schema=schema,
    )


async def test_schema_is_sent_as_json_schema_not_json_object() -> None:
    """Ради этого правка и делалась: json_object допускал ответ любой формы."""
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=chat_completion(ANSWER))

    assert await complete(provider_over(handler)) == {"verdict": "готово"}

    fmt = sent[0]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["schema"] == SCHEMA


async def test_without_schema_stays_on_json_object() -> None:
    """Классификатору схему не передают — режим меняться не должен."""
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=chat_completion(ANSWER))

    await complete(provider_over(handler), schema=None)

    assert sent[0]["response_format"] == {"type": "json_object"}


async def test_server_rejecting_json_schema_falls_back_once() -> None:
    """Прокси, не понимающий формат, не должен ронять оценку целиком."""
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append(body)
        if body["response_format"]["type"] == "json_schema":
            return httpx.Response(400, json={"error": {"message": "unsupported response_format"}})
        return httpx.Response(200, json=chat_completion(ANSWER))

    assert await complete(provider_over(handler)) == {"verdict": "готово"}

    assert len(sent) == 2, "ровно один повтор, не цикл"
    assert sent[1]["response_format"] == {"type": "json_object"}


async def test_other_errors_do_not_trigger_the_fallback() -> None:
    """Откат ловит только «формат не понял».

    Проверяется не число запросов, а формат в них: сам SDK повторяет 5xx
    (`max_retries=2` по умолчанию, отсюда три попытки вместо одной), и это его
    дело. Наша ветка отката при этом сработать не должна — иначе недоступность
    провайдера молча превратилась бы в «схему не поддерживают» и запрос ушёл бы
    в ослабленном режиме.
    """
    formats: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        formats.append(json.loads(request.content)["response_format"]["type"])
        return httpx.Response(500, json={"error": {"message": "upstream is down"}})

    with pytest.raises(openai.InternalServerError):
        await complete(provider_over(handler))

    assert set(formats) == {"json_schema"}, "ослаблять формат на 5xx нельзя"
