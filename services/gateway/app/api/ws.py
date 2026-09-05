"""WebSocket сессии: JSON control/events и binary microphone PCM.

Одно соединение на сессию, JSON-события в обе стороны. Референсный проект
держит два сокета (аудио отдельно от событий) — нам это не нужно, пока ввод
текстовый; в голосовой фазе бинарный канал добавится вторым путём в том же
upgrade-обработчике. См. docs/stt-phase.md.

Инвариант входа: каждое событие валидируется через контракты, а не читается
как свободный dict. Невалидное событие — ошибка клиенту, а не исключение
внутри пайплайна.
"""

import asyncio
import json

from ath_contracts import (
    ErrorEvent,
    FinishSession,
    Ping,
    ServerEvent,
    SpeechAbort,
    SpeechEnd,
    SpeechStart,
    UserMessage,
    parse_client_event,
)
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.clients.scenario_client import ScenarioNotFound
from app.core.config import get_settings
from app.core.logging import bind_session_context, clear_session_context, get_logger
from app.db.engine import session_factory
from app.db.repositories import SqlSessionRepository
from app.orchestrator.pipeline import TurnPipeline
from app.orchestrator.voice_recovery import VoiceRecoveryPlayer
from app.orchestrator.voice_turns import VoiceTurnRegistry

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

    send_lock = asyncio.Lock()

    async def send(event: ServerEvent) -> None:
        async with send_lock:
            await websocket.send_json(event.model_dump(mode="json"))

    pipeline = TurnPipeline(
        session=session,
        ai=app.state.ai,
        speech=app.state.speech,
        send=send,
        max_context_turns=get_settings().max_context_turns,
    )
    settings = get_settings()
    voice = VoiceTurnRegistry(
        session_id=session_id,
        pipeline=pipeline,
        speech=app.state.speech,
        send=send,
        recovery=VoiceRecoveryPlayer(
            speech=app.state.speech,
            send=send,
            session=session,
            cache_dir=settings.voice_recovery_dir,
        ),
        max_capture_seconds=settings.voice_max_capture_seconds,
        max_frame_bytes=settings.voice_max_frame_bytes,
        language=settings.stt_language,
    )

    log.info("ws.connected", scenario_id=session.scenario.id)

    # Инициативу держит агент (§1): персонаж заговаривает сам, не дожидаясь
    # реплики сотрудника.
    #
    # Два условия, а не одно. Пустая история отсекает переподключение посреди
    # сценария (её поднимает _restore_session ниже) — но сама по себе она
    # ненадёжна: ход записывается уже после того, как реплика договорена, и
    # второе подключение, успевшее втиснуться в этот промежуток, увидело бы
    # историю всё ещё пустой. Нулевой счётчик поколений закрывает окно: он
    # растёт синхронно, первым же действием open_session().
    if not session.turns and session.generations.current == 0:
        await pipeline.open_session()

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            frame = message.get("bytes")
            if frame is not None:
                await voice.push(frame)
                continue
            try:
                raw = json.loads(message.get("text") or "")
            except json.JSONDecodeError:
                await send(ErrorEvent(code="invalid_event", message="Ожидался JSON control frame"))
                continue

            try:
                event = parse_client_event(raw)
            except ValidationError as exc:
                await send(
                    ErrorEvent(code="invalid_event", message=exc.errors()[0]["msg"])
                )
                continue

            if isinstance(event, Ping):
                continue

            if isinstance(event, FinishSession):
                await pipeline.handle_finish_request()
                continue

            if isinstance(event, UserMessage):
                # Триггер отмены (§6). Сейчас это отправка реплики, в голосовой
                # фазе — VAD onset; всё, что ниже, не изменится.
                session.avatar_id = event.avatar_id
                await pipeline.handle_user_message(
                    event.text, event.interrupts, avatar_id=event.avatar_id
                )
            elif isinstance(event, SpeechStart):
                # Голосовой ход должен звучать тем же голосом, что и текстовый.
                session.avatar_id = event.avatar_id
                await voice.start(event)
            elif isinstance(event, SpeechEnd):
                await voice.end(str(event.capture_id))
            elif isinstance(event, SpeechAbort):
                await voice.abort(str(event.capture_id))

    except WebSocketDisconnect:
        log.info("ws.disconnected")
    finally:
        await voice.aclose()
        await session.generations.cancel_all()
        await _persist(session)
        clear_session_context()


async def _restore_session(websocket: WebSocket, session_id: str):
    """Поднять сессию из БД в память процесса (перезапуск сервера, reconnect).

    Отрабатывает не только на переподключении: живое состояние появляется в
    реестре лишь когда сокет подключился хотя бы раз, а POST /sessions пишет
    только строку в БД — значит через эту функцию проходит и самое первое
    подключение к свежей сессии.

    Поэтому историю обязательно восстанавливать: по её пустоте выше решается,
    открывать ли сессию приветствием (§1). Без этого персонаж здоровался бы
    заново после каждого разрыва связи посреди сценария.
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
    session.adopt(state)
    log.info(
        "ws.session_restored",
        turns=len(session.turns),
        stage_id=session.current_stage_id,
        current_gen=session.generations.current,
    )
    return session


async def _persist(session) -> None:  # noqa: ANN001
    """Сохранить состояние при закрытии соединения.

    TODO: писать ход сразу по его завершении, а не только на disconnect —
    при падении процесса посреди сессии сейчас теряется весь разговор.
    """
    async with session_factory()() as db:
        await SqlSessionRepository(db).save_snapshot(session.snapshot())
