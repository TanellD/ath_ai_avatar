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
    OpeningKind,
    Persona,
    Report,
    Scenario,
    Stage,
    Turn,
    slot_defaults,
)
from ath_contracts.api import (
    CharacterReplyMeta,
    CharacterReplyRequest,
    ClassifyRequest,
    ClassifyResponse,
    EvaluateRequest,
    EvaluateResponse,
    ScenarioDetailsRequest,
    ScenarioDetailsResponse,
)
from httpx_sse import aconnect_sse
from pydantic import ValidationError

from app.core.logging import get_logger

log = get_logger(__name__)


class EvaluationUnavailable(Exception):
    """Оценку не удалось получить: ai-service или провайдер не ответили.

    Отдельный тип по образцу ScenarioNotFound — чтобы слой API мог отличить
    «не смогли посчитать» от ошибки в данных и не импортировал httpx.
    """


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
        opening_kind: OpeningKind | None = None,
        off_topic_streak: int = 0,
    ) -> AsyncIterator[str | CharacterReplyMeta]:
        """Поток токенов реплики персонажа (быстрая модель, §5).

        Отдаёт токены по мере поступления; финальное событие с action пока
        игнорируем — решение о переходе принимает автомат на основе
        отдельного вызова classify(), а не того, что предложила модель.

        `opening_kind` заполнен, когда персонаж заговорил сам (§1): тогда в
        `user_text` лежит ремарка режиссёра, а не реплика человека.
        """
        payload = CharacterReplyRequest(
            persona=persona,
            stage=stage,
            history=history,
            summary=summary,
            user_text=user_text,
            opening_kind=opening_kind,
            off_topic_streak=off_topic_streak,
        )

        async with aconnect_sse(
            self._client, "POST", "/character/reply", json=payload.model_dump(mode="json")
        ) as source:
            async for sse in source.aiter_sse():
                if sse.event == "done":
                    return
                if sse.event == "meta":
                    yield CharacterReplyMeta.model_validate_json(sse.data)
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

    async def fill_scenario_details(self, scenario: Scenario) -> dict[str, str]:
        """Детали слотов под этот прогон (§7): имена, компании, продукты, цифры.

        Никогда не бросает. Значения `example` из самого сценария — полноценный
        запасной путь: бриф останется читаемым, персонаж — согласованным с ним,
        и потеряется ровно одно — разнообразие между прогонами. Уронить из-за
        этого старт тренировки было бы несоразмерно.

        Тайм-аут короткий по той же причине: вызов стоит в задержке старта, и
        лучше отдать сотруднику сценарий с примерами, чем держать его перед
        пустым экраном.
        """
        if not scenario.slots:
            return {}

        payload = ScenarioDetailsRequest(
            title=scenario.title,
            persona_role=scenario.persona.role,
            briefing=scenario.briefing,
            slots=scenario.slots,
        )
        try:
            response = await self._client.post(
                "/scenario/details", json=payload.model_dump(mode="json"), timeout=15.0
            )
            response.raise_for_status()
            return ScenarioDetailsResponse.model_validate(response.json()).values
        except (httpx.HTTPError, ValidationError) as exc:
            # Тип обязателен: у httpx.ReadTimeout — самого частого здесь исхода —
            # str(exc) пустой, и в логе оставалось бы `error=` без единого слова
            # о том, что вообще произошло.
            log.warning(
                "ai.scenario_details_failed",
                scenario_id=scenario.id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return slot_defaults(scenario)

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
        try:
            response = await self._client.post(
                "/evaluate", json=payload.model_dump(mode="json"), timeout=120.0
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            # Оценка длинного разговора сильной моделью — самый долгий вызов в
            # системе, и он реально отваливается: сторонний шлюз отдавал 524 на
            # транскрипте в 40 реплик. Наверх идёт своё исключение, чтобы API
            # не пришлось знать про httpx и можно было ответить внятно.
            raise EvaluationUnavailable(str(exc)) from exc

        return EvaluateResponse.model_validate(response.json()).report
