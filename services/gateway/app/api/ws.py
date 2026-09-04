"""WebSocket сессии — Claude.md §6, §7.

Одно соединение на сессию, JSON-события в обе стороны. Референсный проект
держит два сокета (аудио отдельно от событий) — нам это не нужно, пока ввод
текстовый; в голосовой фазе бинарный канал добавится вторым путём в том же
upgrade-обработчике. См. docs/stt-phase.md.

Инвариант входа: каждое событие валидируется через контракты, а не читается
как свободный dict. Невалидное событие — ошибка клиенту, а не исключение
внутри пайплайна.
"""

from ath_contracts import ErrorEvent, Ping, ServerEvent, UserMessage, parse_client_event
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.clients.scenario_client import ScenarioNotFound
from app.core.config import get_settings
from app.core.logging import bind_session_context, clear_session_context, get_logger
from app.db.engine import session_factory
from app.db.repositories import SqlSessionRepository
from app.orchestrator.pipeline import TurnPipeline

router = APIRouter()
log = get_logger(__name__)


@router.websocket("/ws/session/{session_id}")
async def session_socket(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    bind_session_context(session_id)

    app = websocket.app
    registry = app.state.sessions

    session = registry.get(session_id)
    if session is None:
        session = await _restore_session(websocket, session_id)
        if session is None:
            return

    async def send(event: ServerEvent) -> None:
        await websocket.send_json(event.model_dump(mode="json"))

    pipeline = TurnPipeline(
        session=session,
        ai=app.state.ai,
        speech=app.state.speech,
        send=send,
        max_context_turns=get_settings().max_context_turns,
    )

    log.info("ws.connected", scenario_id=session.scenario.id)

    # TODO: отправить agent_opening текущего этапа сразу после подключения,
    # чтобы инициативу держал агент (§1) — сейчас первый ход делает человек.

    try:
        while True:
            raw = await websocket.receive_json()

            try:
                event = parse_client_event(raw)
            except ValidationError as exc:
                await send(
                    ErrorEvent(code="invalid_event", message=exc.errors()[0]["msg"])
                )
                continue

            if isinstance(event, Ping):
                continue

            if isinstance(event, UserMessage):
                # Триггер отмены (§6). Сейчас это отправка реплики, в голосовой
                # фазе — VAD onset; всё, что ниже, не изменится.
                await pipeline.handle_user_message(
                    event.text, event.interrupts, avatar_id=event.avatar_id
                )

    except WebSocketDisconnect:
        log.info("ws.disconnected")
    finally:
        await session.generations.cancel_all()
        await _persist(session)
        clear_session_context()


async def _restore_session(websocket: WebSocket, session_id: str):
    """Поднять сессию из БД в память процесса (перезапуск сервера, reconnect).

    TODO: восстанавливать turns и stage_history, а не только идентификаторы —
    сейчас после переподключения персонаж теряет контекст разговора.
    """
    async with session_factory()() as db:
        state = await SqlSessionRepository(db).get(session_id)

    if state is None:
        await websocket.close(code=4404, reason="session not found")
        log.warning("ws.session_not_found")
        return None

    try:
        scenario = await websocket.app.state.scenario.get(state.scenario_id)
    except ScenarioNotFound:
        await websocket.close(code=4404, reason="scenario not found")
        return None

    session = websocket.app.state.sessions.create(session_id, scenario)
    session.current_stage_id = state.current_stage
    return session


async def _persist(session) -> None:  # noqa: ANN001
    """Сохранить состояние при закрытии соединения.

    TODO: писать ход сразу по его завершении, а не только на disconnect —
    при падении процесса посреди сессии сейчас теряется весь разговор.
    """
    async with session_factory()() as db:
        await SqlSessionRepository(db).save_snapshot(session.snapshot())
