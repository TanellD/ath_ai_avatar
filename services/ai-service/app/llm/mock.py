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
        """Возвращает минимальный валидный ответ по форме запрошенной схемы.

        TODO: сейчас понимает только классификацию. Для /evaluate нужен ответ
        формы Report — его удобнее собрать в evaluation/report_builder.py из
        реального транскрипта, чтобы цитаты были настоящими, а не выдуманными
        заглушкой (иначе тестировать проверяемость отчёта бессмысленно).
        """
        await asyncio.sleep(0.1)
        log.debug("llm.mock.complete_json")
        return json.loads('{"classification": "incomplete", "reason": "mock provider"}')
