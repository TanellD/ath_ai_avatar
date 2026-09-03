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

    classification = Classification(result["classification"])
    log.info("classify.done", stage_id=payload.stage.id, classification=classification.value)

    return ClassifyResponse(classification=classification, reason=result.get("reason", ""))
