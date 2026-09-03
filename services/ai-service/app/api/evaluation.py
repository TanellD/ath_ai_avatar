"""Итоговая оценка — Claude.md §5, §7.

Один вызов сильной модели после завершения сессии. Здесь не важна скорость и
критически важна проверяемость результата, поэтому ответ проходит через
report_builder, который отбраковывает отчёты с непроверяемыми цитатами.
"""

from ath_contracts.api import EvaluateRequest, EvaluateResponse
from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import get_settings
from app.core.logging import get_logger
from app.evaluation.prompts import (
    build_evaluation_system,
    build_report_schema,
    build_transcript_message,
)
from app.evaluation.report_builder import InvalidReportError, build_report

router = APIRouter(tags=["evaluation"])
log = get_logger(__name__)


@router.post("/evaluate", response_model=EvaluateResponse)
async def evaluate(payload: EvaluateRequest, request: Request) -> EvaluateResponse:
    settings = get_settings()
    provider = request.app.state.llm

    raw = await provider.complete_json(
        system=build_evaluation_system(payload.scenario),
        messages=[{"role": "user", "content": build_transcript_message(payload.transcript)}],
        model=settings.llm_strong_model,
        max_tokens=settings.evaluation_max_tokens,
        temperature=settings.evaluation_temperature,
        schema=build_report_schema(payload.scenario),
    )

    try:
        report = build_report(
            session_id=payload.session_id,
            scenario=payload.scenario,
            transcript=payload.transcript,
            raw=raw,
            duration_sec=payload.duration_sec,
            stages_completed=payload.stages_completed,
            stages_total=payload.stages_total,
        )
    except InvalidReportError as exc:
        # TODO: один повтор с указанием на конкретную непрошедшую цитату перед
        # тем, как сдаваться. Отдать методисту отчёт с выдуманной цитатой хуже,
        # чем не отдать никакого, поэтому пока честная ошибка.
        log.error("evaluate.invalid_report", session_id=payload.session_id, error=str(exc))
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    log.info(
        "evaluate.done", session_id=payload.session_id, total_score=report.total_score
    )
    return EvaluateResponse(report=report)
