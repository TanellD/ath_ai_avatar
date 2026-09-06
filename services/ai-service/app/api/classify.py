"""Классификация ответа сотрудника — Claude.md §5.

Модель отвечает на один вопрос: выполнен ли критерий этапа. Куда двигаться
дальше — не её дело; это решает автомат в gateway.
"""

from ath_contracts import Classification
from ath_contracts.api import ClassifyRequest, ClassifyResponse
from fastapi import APIRouter, Request

from app.character.prompts import (
    CLASSIFICATION_SCHEMA,
    build_classifier_system,
    build_messages,
)
from app.core.config import get_settings
from app.core.logging import get_logger

router = APIRouter(tags=["classify"])
log = get_logger(__name__)


@router.post("/classify", response_model=ClassifyResponse)
async def classify(payload: ClassifyRequest, request: Request) -> ClassifyResponse:
    settings = get_settings()
    provider = request.app.state.llm

    result = await provider.complete_json(
        system=build_classifier_system(payload.stage),
        messages=build_messages(payload.history, "", payload.user_text),
        # Быстрая модель: классификация из трёх вариантов не требует сильной,
        # а вызов идёт на каждый ход и попадает в бюджет ответа.
        model=settings.llm_fast_model,
        max_tokens=256,
        temperature=0.0,
        schema=CLASSIFICATION_SCHEMA,
    )

    try:
        # `result` типизирован как dict по контракту LlmProvider.complete_json,
        # но контракт — не гарантия: json.loads на выход модели может дать
        # list/str/число, если модель ответила JSON-массивом или скаляром
        # вместо объекта — тогда и `result["classification"]`, и `.get(...)`
        # ниже кидают не (KeyError, ValueError), а TypeError/AttributeError.
        # Явная проверка типа переводит любой такой случай в один и тот же
        # путь деградации, а не оставляет часть форм ответа непойманными.
        if not isinstance(result, dict):
            raise TypeError(f"complete_json вернул {type(result).__name__}, ожидался object")
        classification = Classification(result["classification"])
        reason = result.get("reason", "")
    except (KeyError, ValueError, TypeError):
        # Модель вернула JSON без ожидаемого поля/значения (наблюдалось на
        # локальных Qwen через Ollama при недостаточно строгом response_format —
        # см. openai_compatible.py). gateway (pipeline._advance_stage) и так
        # ловит любое исключение отсюда и подставляет INCOMPLETE, но это
        # превращалось в необработанный 500 и шумный traceback вместо
        # предсказуемого «этап не засчитан» — той же деградации, что и на
        # честном INCOMPLETE. Явный дефолт здесь дешевле и не теряет
        # диагностику: сырой ответ модели остаётся в логе.
        log.warning("classify.malformed_response", stage_id=payload.stage.id, raw=result)
        classification = Classification.INCOMPLETE
        reason = ""

    log.info("classify.done", stage_id=payload.stage.id, classification=classification.value)

    return ClassifyResponse(classification=classification, reason=reason)
