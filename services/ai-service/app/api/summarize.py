"""Сжатие вытесненной из окна контекста истории — Claude.md §5.

Без этого `context_window.build_context` просто отрезает всё, что не влезло в
последние `max_context_turns` ходов, — сотрудник упомянул что-то на третьей
реплике, а на восьмой персонаж (и классификатор) уже не видит этого вообще:
`session.summary` был заведён в контракте заранее, но ничего его не
заполняло (TODO в context_window.py). Отсюда и «теряется контекст, когда
сообщений становится больше».
"""

from ath_contracts.api import SummarizeRequest, SummarizeResponse
from fastapi import APIRouter, Request

from app.core.config import get_settings
from app.core.logging import get_logger

router = APIRouter(tags=["summarize"])
log = get_logger(__name__)

_SYSTEM = """\
Ты сжимаешь начало тренировочного диалога в краткую выжимку для языковой
модели, которая продолжит разговор дальше, уже не видя эти реплики целиком.

Сохрани только то, что реально понадобится дальше: названные факты, цифры,
имена, договорённости, возражения и то, как их сняли. Не пересказывай
формулировки дословно и не оценивай качество диалога — это не отчёт, а
рабочая память для модели.

Пиши от третьего лица, 3-6 предложений, без разметки.
"""

_SCHEMA = {
    "title": "ContextSummary",
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}


def _build_user_message(payload: SummarizeRequest) -> str:
    lines = [f"{turn.role.value}: {turn.text}" for turn in payload.evicted]
    evicted_text = "\n".join(lines)
    if not payload.previous_summary:
        return f"Новые реплики для сжатия:\n{evicted_text}"
    return (
        f"Уже есть выжимка более раннего разговора:\n{payload.previous_summary}\n\n"
        f"Дополни её новыми репликами, слив в одну связную выжимку:\n{evicted_text}"
    )


@router.post("/summarize", response_model=SummarizeResponse)
async def summarize(payload: SummarizeRequest, request: Request) -> SummarizeResponse:
    settings = get_settings()
    provider = request.app.state.llm

    if not payload.evicted:
        # Нечего сжимать — быстрый путь без обращения к модели (например,
        # повторный вызов на той же границе окна).
        return SummarizeResponse(summary=payload.previous_summary)

    result = await provider.complete_json(
        system=_SYSTEM,
        messages=[{"role": "user", "content": _build_user_message(payload)}],
        # Быстрая модель: суммаризация — не задача, где нужна сильная,
        # а вызов по объёму сопоставим с репликой персонажа.
        model=settings.llm_fast_model,
        max_tokens=400,
        temperature=0.2,
        schema=_SCHEMA,
    )

    summary = result.get("summary", "").strip()
    if not summary:
        # Модель дала пустой ответ — откатываемся к прежней выжимке, а не
        # стираем контекст, который уже был накоплен.
        log.warning("summarize.empty_result", evicted_count=len(payload.evicted))
        return SummarizeResponse(summary=payload.previous_summary)

    # Единственное место, где итоговая выжимка вообще видна снаружи —
    # session.summary не персистится и не отдаётся ни в один API-ответ
    # (§7 её сознательно не включает: это рабочая память конвейера, не
    # продуктовый контракт). Без этого лога проверить на живом прогоне,
    # что вытесненный контекст реально попал в выжимку, а не потерялся,
    # можно было только патчем кода.
    log.info("summarize.done", evicted_count=len(payload.evicted), summary=summary)
    return SummarizeResponse(summary=summary)
