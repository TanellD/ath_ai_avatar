"""Клиент ai-service: реплики персонажа, классификация, итоговая оценка.

Транспорт для реплики — SSE, потому что нужен поток токенов: время до первого
токена и есть половина бюджета метрики 1 (§9).

Отмена: httpx закрывает соединение при выходе из `async with`, а выход
происходит по `asyncio.CancelledError` от GenerationRegistry.cancel(). Отдельный
AbortController не нужен — отмена задачи и есть отмена запроса.
"""

import json
from collections.abc import AsyncIterator

import httpx
from ath_contracts import (
    Classification,
    Persona,
    Report,
    Scenario,
    Stage,
    Turn,
)
from ath_contracts.api import (
    CharacterReplyRequest,
    ClassifyRequest,
    ClassifyResponse,
    EvaluateRequest,
    EvaluateResponse,
)
from httpx_sse import aconnect_sse

from app.core.logging import get_logger

log = get_logger(__name__)


class AiClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def ping(self) -> None:
        """Для GET /ready. Кидает httpx.HTTPError, если сервис не отвечает."""
        response = await self._client.get("/health", timeout=3.0)
        response.raise_for_status()

    async def stream_character_reply(
        self,
        persona: Persona,
        stage: Stage,
        history: list[Turn],
        summary: str,
        user_text: str,
    ) -> AsyncIterator[str]:
        """Поток токенов реплики персонажа (быстрая модель, §5).

        Отдаёт токены по мере поступления; финальное событие с action пока
        игнорируем — решение о переходе принимает автомат на основе
        отдельного вызова classify(), а не того, что предложила модель.
        """
        payload = CharacterReplyRequest(
            persona=persona,
            stage=stage,
            history=history,
            summary=summary,
            user_text=user_text,
        )

        async with aconnect_sse(
            self._client, "POST", "/character/reply", json=payload.model_dump(mode="json")
        ) as source:
            async for sse in source.aiter_sse():
                if sse.event == "done":
                    return
                if sse.event == "token":
                    yield json.loads(sse.data)["text"]

    async def classify(
        self, stage: Stage, history: list[Turn], user_text: str
    ) -> Classification:
        """complete | incomplete | off_topic (§5)."""
        payload = ClassifyRequest(stage=stage, history=history, user_text=user_text)
        response = await self._client.post("/classify", json=payload.model_dump(mode="json"))
        response.raise_for_status()
        return ClassifyResponse.model_validate(response.json()).classification

    async def evaluate(
        self,
        session_id: str,
        scenario: Scenario,
        transcript: list[Turn],
        duration_sec: int,
        stages_completed: int,
        stages_total: int,
    ) -> Report:
        """Один вызов сильной модели после завершения сессии (§5)."""
        payload = EvaluateRequest(
            session_id=session_id,
            scenario=scenario,
            transcript=transcript,
            duration_sec=duration_sec,
            stages_completed=stages_completed,
            stages_total=stages_total,
        )
        response = await self._client.post(
            "/evaluate", json=payload.model_dump(mode="json"), timeout=120.0
        )
        response.raise_for_status()
        return EvaluateResponse.model_validate(response.json()).report
