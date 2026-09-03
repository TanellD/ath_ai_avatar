"""HTTP-ручки сессии.

Сама тренировка идёт по WebSocket (api/ws.py); здесь только то, что удобнее
обычным запросом: создание сессии, состояние, готовый отчёт для методиста.
"""

import uuid

from ath_contracts import Report, SessionState
from ath_contracts.api import CreateSessionRequest, CreateSessionResponse
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

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
