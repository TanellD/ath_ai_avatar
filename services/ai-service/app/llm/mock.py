"""Заглушка LLM. Провайдер по умолчанию — сервис поднимается без ключей.

Отдаёт правдоподобную по форме реплику: длиной в пару предложений, с
задержками между токенами. Форма важнее содержания — на ней проверяются
сплиттер предложений, поток TTS и отмена по gen_id, а не качество диалога.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from app.core.logging import get_logger
from app.llm.base import LlmProvider

log = get_logger(__name__)

_FIRST_TOKEN_DELAY_SEC = 0.35
"""Середина бюджета «LLM: первый токен» — 300-800 мс (Claude.md §9)."""

_TOKEN_DELAY_SEC = 0.02

_REPLY = (
    "Так, хорошо. У меня сейчас другой поставщик, и цена там ниже вашей. "
    "Объясните, за что я должна переплачивать?"
)


class MockLlmProvider(LlmProvider):
    @property
    def name(self) -> str:
        return "mock"

    async def stream(
        self,
        system: str,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[str]:
        await asyncio.sleep(_FIRST_TOKEN_DELAY_SEC)

        # Режем по словам с пробелами, чтобы сплиттер предложений получал вход
        # той же формы, что и от настоящей модели.
        for word in _REPLY.split(" "):
            yield word + " "
            await asyncio.sleep(_TOKEN_DELAY_SEC)

    async def complete_json(
        self,
        system: str,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Возвращает минимальный валидный ответ по форме запрошенной схемы."""
        await asyncio.sleep(0.1)

        properties = (schema or {}).get("properties", {})
        if "verdict" in properties:
            log.debug("llm.mock.complete_json", kind="report")
            return _mock_report(properties, messages)

        log.debug("llm.mock.complete_json", kind="classification")
        return json.loads('{"classification": "incomplete", "reason": "mock provider"}')


def _mock_report(properties: dict[str, Any], messages: list[dict[str, str]]) -> dict[str, Any]:
    """Отчёт-заглушка, который переживёт проверки report_builder.

    Две вещи здесь не косметические:

    - `criterion_id` берётся из enum'а схемы: `build_report_schema` кладёт туда
      реальные id рубрики сценария, а построитель отчёта проверяет покрытие.
    - `evidence` обязана быть ДОСЛОВНОЙ подстрокой реплики сотрудника, иначе
      отчёт отвергается (evaluation/report_builder.py). Поэтому цитата не
      выдумывается, а берётся из транскрипта в сообщениях — заодно это
      единственный способ проверять на mock'е ту самую проверяемость отчёта,
      ради которой цитаты и заведены (§7).
    """
    scores_schema = properties.get("scores", {}).get("items", {}).get("properties", {})
    criterion_ids: list[str] = scores_schema.get("criterion_id", {}).get("enum", [])
    quote = _first_user_line(messages)

    return {
        "verdict": "Отчёт заглушки: провайдер LLM не настроен, оценка не проводилась.",
        "total_score": 0.0,
        "scores": [
            {
                "criterion_id": criterion_id,
                "score": 0,
                "evidence": quote,
                "comment": "Заглушка: реальной оценки не было.",
            }
            for criterion_id in criterion_ids
        ],
    }


def _first_user_line(messages: list[dict[str, str]]) -> str:
    """Первая реплика сотрудника из транскрипта.

    Формат задаёт evaluation/prompts.py::build_transcript_message —
    `[{index}] СОТРУДНИК: {text}`. Если сотрудник не сказал ничего (сессию
    завершили сразу после приветствия персонажа), цитировать нечего: пустая
    строка не пройдёт валидацию Report, и это правильно — отчёта без реплик
    сотрудника быть не должно.
    """
    marker = "] СОТРУДНИК: "
    for message in messages:
        for line in message.get("content", "").splitlines():
            head, sep, text = line.partition(marker)
            if sep and head.startswith("["):
                return text.strip()
    return ""
