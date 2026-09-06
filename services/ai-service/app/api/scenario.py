"""Черновики сценария методисту — Claude.md §7.

Сценарий создаётся «из шаблона, из сгенерированного черновика или с нуля».
Первый и третий пути закрывает CRUD scenario-service, второй — эти две ручки.

Обе отдают ЧЕРНОВИК в форму редактора, а не сохраняют сценарий: методист
смотрит и правит перед сохранением. Ответственность за методику остаётся у
человека — модель ускоряет заполнение, но не решает, чему учить.

Модель разная и не по недосмотру. Развернуть пару строк в связный сценарий —
задача на понимание, вызов редкий и не в бюджете диалога, поэтому сильная.
Рубрика к уже описанным этапам — работа поверх готового текста, там хватает
быстрой.

Повтора при ошибке нет — как и во всём сервисе (см. TODO в evaluation.py).
Черновик, в отличие от отчёта, ничем не рискует: методист просто нажимает
кнопку ещё раз.
"""

from collections.abc import Callable

from ath_contracts.api import (
    RubricDraft,
    RubricDraftRequest,
    ScenarioDetailsRequest,
    ScenarioDetailsResponse,
    ScenarioDraftRequest,
    ScenarioDraftResponse,
)
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.scenario.drafts import build_details, build_rubric_draft, build_scenario_draft
from app.scenario.prompts import (
    build_details_message,
    build_details_schema,
    build_details_system,
    build_draft_message,
    build_draft_schema,
    build_draft_system,
    build_rubric_message,
    build_rubric_schema,
    build_rubric_system,
)

router = APIRouter(prefix="/scenario", tags=["scenario"])
log = get_logger(__name__)

_DRAFT_MAX_TOKENS = 4000
"""Сценарий на 4 этапа и 4 критерия — того же порядка текст, что и отчёт."""

_RUBRIC_MAX_TOKENS = 2000

_DETAILS_MAX_TOKENS = 500
"""Полсотни коротких значений, а не текст."""


@router.post("/draft", response_model=ScenarioDraftResponse)
async def draft_scenario(payload: ScenarioDraftRequest, request: Request) -> ScenarioDraftResponse:
    settings = get_settings()
    provider = request.app.state.llm

    raw = await provider.complete_json(
        system=build_draft_system(),
        messages=[
            {
                "role": "user",
                "content": build_draft_message(
                    payload.brief, payload.stages_count, payload.rubric_count
                ),
            }
        ],
        model=settings.llm_strong_model,
        max_tokens=_DRAFT_MAX_TOKENS,
        temperature=settings.character_temperature,
        schema=build_draft_schema(payload.stages_count, payload.rubric_count),
    )

    draft = _build(build_scenario_draft, raw, "draft")
    log.info("scenario.draft.done", stages=len(draft.stages), rubric=len(draft.rubric))
    return draft


@router.post("/rubric", response_model=RubricDraft)
async def draft_rubric(payload: RubricDraftRequest, request: Request) -> RubricDraft:
    settings = get_settings()
    provider = request.app.state.llm

    raw = await provider.complete_json(
        system=build_rubric_system(),
        messages=[
            {
                "role": "user",
                "content": build_rubric_message(
                    payload.title, payload.persona, payload.stages, payload.count
                ),
            }
        ],
        model=settings.llm_fast_model,
        max_tokens=_RUBRIC_MAX_TOKENS,
        temperature=settings.character_temperature,
        schema=build_rubric_schema(payload.count),
    )

    draft = _build(build_rubric_draft, raw, "rubric")
    log.info("scenario.rubric.done", count=len(draft.items))
    return draft


@router.post("/details", response_model=ScenarioDetailsResponse)
async def scenario_details(
    payload: ScenarioDetailsRequest, request: Request
) -> ScenarioDetailsResponse:
    """Детали под один прогон: имена, компании, продукты, цифры.

    Зовётся не методистом, а gateway при создании сессии, поэтому попадает в
    задержку старта тренировки — отсюда быстрая модель и небольшой лимит: это
    полсотни коротких значений, а не текст.

    Ошибку наружу отдаём как есть: у вызывающего (gateway) есть запасной путь —
    значения `example` из самого сценария. Косметическая деталь не имеет права
    не дать тренировке начаться.
    """
    settings = get_settings()
    provider = request.app.state.llm

    raw = await provider.complete_json(
        system=build_details_system(),
        messages=[
            {
                "role": "user",
                "content": build_details_message(
                    payload.title, payload.persona_role, payload.briefing
                ),
            }
        ],
        model=settings.llm_fast_model,
        max_tokens=_DETAILS_MAX_TOKENS,
        # Смысл ручки — в разнообразии между прогонами: одни и те же детали на
        # пятом прогоне работают против §7.
        temperature=1.0,
        schema=build_details_schema(payload.slots),
    )

    values = build_details(raw, payload.slots)
    log.info("scenario.details.done", slots=len(values))
    return ScenarioDetailsResponse(values=values)


def _build[T: (ScenarioDraftResponse, RubricDraft)](
    builder: Callable[[dict], T], raw: dict, kind: str
) -> T:
    """Ответ не по контракту — это 502, а не 500.

    Черновик собирается из того, что вернула модель через возможный сторонний
    шлюз (§10). Если оттуда пришло что-то не той формы, виноват не запрос
    методиста — и он должен увидеть «попробуйте ещё раз», а не «ошибка
    сервера».
    """
    try:
        return builder(raw)
    except ValidationError as exc:
        log.error("scenario.draft.invalid", kind=kind, error=str(exc))
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "модель вернула черновик не по контракту — попробуйте ещё раз",
        ) from exc
