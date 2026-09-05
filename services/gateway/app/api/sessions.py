"""HTTP-ручки сессии.

Сама тренировка идёт по WebSocket (api/ws.py); здесь только то, что удобнее
обычным запросом: создание сессии, состояние, готовый отчёт для методиста.
"""

import uuid

from ath_contracts import Report, SessionState
from ath_contracts.api import (
    CreateSessionRequest,
    CreateSessionResponse,
    SessionListResponse,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.ai_client import EvaluationUnavailable
from app.clients.scenario_client import ScenarioNotFound
from app.core.logging import get_logger
from app.db.engine import get_session
from app.db.repositories import SqlReportRepository, SqlSessionRepository
from app.db.seed import DEFAULT_EMPLOYEE_ID

router = APIRouter(prefix="/sessions", tags=["sessions"])
log = get_logger(__name__)


@router.post("", response_model=CreateSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: CreateSessionRequest,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> CreateSessionResponse:
    """Создать сессию под сценарий и вернуть адрес WebSocket.

    Сценарий подтягивается сразу, чтобы несуществующий scenario_id падал здесь
    с понятной 404, а не внутри уже открытого сокета.
    """
    try:
        scenario = await request.app.state.scenario.get(payload.scenario_id)
    except ScenarioNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    session_id = str(uuid.uuid4())
    state = SessionState(
        session_id=session_id,
        scenario_id=scenario.id,
        current_stage=scenario.stages[0].id,
    )
    # Единственный сотрудник, пока авторизации нет (Claude.md §4) — см.
    # app/db/seed.py. Когда появятся реальные аккаунты, здесь будет
    # request.state.user_id вместо константы.
    await SqlSessionRepository(db).create(state, user_id=DEFAULT_EMPLOYEE_ID)

    log.info("session.created", session_id=session_id, scenario_id=scenario.id)
    return CreateSessionResponse(
        session_id=session_id,
        scenario_id=scenario.id,
        ws_url=f"/ws/session/{session_id}",
    )


@router.get("", response_model=SessionListResponse)
async def list_sessions(db: AsyncSession = Depends(get_session)) -> SessionListResponse:
    """Список сессий для методиста (§2) — отсюда он попадает в отчёт.

    Объявлено ДО `/{session_id}`: FastAPI разбирает маршруты по порядку, и
    более общий шаблон, стоящий раньше, перехватил бы пустой путь.
    """
    items = await SqlSessionRepository(db).list_summaries()
    return SessionListResponse(items=items)


@router.get("/{session_id}", response_model=SessionState)
async def get_session_state(
    session_id: str, db: AsyncSession = Depends(get_session)
) -> SessionState:
    state = await SqlSessionRepository(db).get(session_id)
    if state is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return state


@router.get("/{session_id}/report", response_model=Report)
async def get_report(session_id: str, db: AsyncSession = Depends(get_session)) -> Report:
    """Отчёт методисту (§7). 404 до завершения сессии — отчёт формируется один
    раз, в конце."""
    report = await SqlReportRepository(db).get(session_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "report is not ready")
    return report


@router.post("/{session_id}/report", response_model=Report)
async def rebuild_report(
    session_id: str, request: Request, db: AsyncSession = Depends(get_session)
) -> Report:
    """Пересчитать оценку и перезаписать отчёт.

    Оценка запускается один раз, при завершении сессии, — и этого мало. Она
    могла пройти на заглушке (`LLM_PROVIDER=mock` — дефолт docker-compose) или
    упасть: `pipeline._evaluate_and_store` в этом случае логирует и выходит,
    чтобы не ломать сотруднику выход. До появления этой ручки исправить такую
    сессию можно было только правкой БД руками.

    Синхронно, в отличие от завершения: там оверлей не должен ждать сильную
    модель, а здесь методист пришёл именно за результатом.
    """
    state = await SqlSessionRepository(db).get(session_id)
    if state is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    if not state.turns:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "session has no turns to evaluate"
        )

    try:
        scenario = await request.app.state.scenario.get(state.scenario_id)
    except ScenarioNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    try:
        report = await request.app.state.ai.evaluate(
            session_id=session_id,
            scenario=scenario,
            transcript=state.turns,
            duration_sec=_duration_sec(state),
            stages_completed=len(state.stage_history),
            stages_total=len(scenario.stages),
        )
    except EvaluationUnavailable as exc:
        # Провайдер не ответил — на длинных транскриптах это реальный исход
        # (сторонний шлюз отдавал 524 на 40 репликах). Прежний отчёт при этом
        # остаётся нетронутым, повторить можно той же кнопкой.
        log.warning("session.report_rebuild_failed", session_id=session_id, error=str(exc))
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT,
            "оценка не успела посчитаться — попробуйте ещё раз",
        ) from exc

    await SqlReportRepository(db).save(report)

    log.info("session.report_rebuilt", session_id=session_id, total_score=report.total_score)
    return report


def _duration_sec(state: SessionState) -> int:
    """Длительность по последнему ходу.

    Живого `elapsed_sec` здесь нет — сессия давно закрыта, и таймер её процесса
    не пережил. `ts` последнего хода отсчитывается от старта сессии, так что
    это та же величина с точностью до хвоста после последней реплики.
    """
    return int(state.turns[-1].ts) if state.turns else 0
