"""Итоговая оценка — Claude.md §5, §7.

Один вызов сильной модели после завершения сессии. Здесь не важна скорость и
критически важна проверяемость результата, поэтому ответ проходит через
report_builder, который отбраковывает отчёты с непроверяемыми цитатами.
"""

import json

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

# Один повтор с указанием на конкретную непрошедшую проверку, а не сразу
# сдаваться на первом отказе. Больше одного повтора не делаем: если модель не
# исправилась, увидев точную причину, третья попытка почти наверняка повторит
# тот же сбой — а методист и так ждёт синхронный ответ.
_MAX_ATTEMPTS = 2


@router.post("/evaluate", response_model=EvaluateResponse)
async def evaluate(payload: EvaluateRequest, request: Request) -> EvaluateResponse:
    settings = get_settings()
    provider = request.app.state.llm

    system = build_evaluation_system(payload.scenario)
    schema = build_report_schema(payload.scenario)
    messages = [{"role": "user", "content": build_transcript_message(payload.transcript)}]

    last_error: InvalidReportError | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        raw = await provider.complete_json(
            system=system,
            messages=messages,
            model=settings.llm_strong_model,
            max_tokens=settings.evaluation_max_tokens,
            temperature=settings.evaluation_temperature,
            schema=schema,
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
                # Провайдер + модель: отчёт заглушки обязан быть опознаваем.
                model=f"{provider.name}/{settings.llm_strong_model}",
            )
        except InvalidReportError as exc:
            last_error = exc
            if attempt < _MAX_ATTEMPTS:
                log.warning(
                    "evaluate.invalid_report_retrying",
                    session_id=payload.session_id,
                    attempt=attempt,
                    error=str(exc),
                )
                # Правим курсом на конкретно найденную ошибку — общее «попробуй
                # ещё раз» с высокой вероятностью воспроизвело бы тот же сбой
                # (модель пересказывает вместо цитаты, пропускает критерий и т.п.).
                messages = [
                    *messages,
                    {"role": "assistant", "content": json.dumps(raw, ensure_ascii=False)},
                    {
                        "role": "user",
                        "content": (
                            f"Твой предыдущий ответ не прошёл проверку: {exc}. "
                            "Пришли исправленный JSON той же схемы, устранив именно "
                            "эту ошибку — цитаты дословно из реплик сотрудника, "
                            "каждый критерий рубрики ровно один раз."
                        ),
                    },
                ]
                continue
            # Отдать методисту отчёт с выдуманной цитатой хуже, чем не отдать
            # никакого, поэтому после исчерпанных попыток — честная ошибка.
            log.error(
                "evaluate.invalid_report",
                session_id=payload.session_id,
                attempts=attempt,
                error=str(exc),
            )
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

        log.info(
            "evaluate.done",
            session_id=payload.session_id,
            total_score=report.total_score,
            attempts=attempt,
        )
        return EvaluateResponse(report=report)

    # Недостижимо: цикл на _MAX_ATTEMPTS завершается либо return, либо raise.
    raise AssertionError("unreachable") from last_error
