"""WebSocket синтеза — Claude.md §3, §10.

Протокол: первый `TtsRequest` задаёт голос и может завершать одиночный запрос.
При `text_end=false` следующие `TtsTextChunk` дополняют ту же реплику, пока
финальный кадр не завершит единый Soniox stream. Отмена поколения по-прежнему
закрывает WebSocket и не требует отдельного управляющего сообщения.

`gen_id` сервис не интерпретирует: он только возвращает его в каждом чанке,
чтобы gateway мог отфильтровать хвост, не сопоставляя ответы по порядку.
"""

import base64
import json
from collections.abc import AsyncIterator

from ath_contracts.api import TtsChunk, TtsRequest, TtsTextChunk
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.core.logging import get_logger

router = APIRouter()
log = get_logger(__name__)


@router.websocket("/tts/stream")
async def tts_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    provider = websocket.app.state.tts

    try:
        raw = await websocket.receive_text()
        request = TtsRequest.model_validate(json.loads(raw))
    except (ValidationError, json.JSONDecodeError) as exc:
        log.warning("tts.invalid_request", error=str(exc))
        await websocket.close(code=4400, reason="invalid TtsRequest")
        return
    except WebSocketDisconnect:
        return

    log.debug(
        "tts.stream_started",
        gen_id=request.gen_id,
        seq=request.seq,
        chars=len(request.text),
        provider=provider.name,
    )

    seq = request.seq

    async def incoming_text() -> AsyncIterator[str]:
        if request.text:
            yield request.text
        if request.text_end:
            return
        while True:
            raw_chunk = await websocket.receive_text()
            text_chunk = TtsTextChunk.model_validate(json.loads(raw_chunk))
            if text_chunk.text:
                yield text_chunk.text
            if text_chunk.text_end:
                return

    try:
        async for chunk in provider.synthesize_stream(
            incoming_text(),
            request.voice_id,
            request.emotion,
            request.intensity,
            request.enhanced_prosody,
        ):
            payload = TtsChunk(
                gen_id=request.gen_id,
                seq=seq,
                data=base64.b64encode(chunk.data).decode("ascii"),
                format="wav",
                sample_rate=chunk.sample_rate,
                is_final=chunk.is_final,
                subtitle_text=chunk.subtitle_text,
                subtitle_start_ms=chunk.subtitle_start_ms,
                subtitle_end_ms=chunk.subtitle_end_ms,
            )
            await websocket.send_text(payload.model_dump_json())
            seq += 1

    except WebSocketDisconnect:
        # Штатный путь при перебивании: gateway снял задачу и закрыл сокет.
        log.info("tts.stream_interrupted", gen_id=request.gen_id)
        return
    except NotImplementedError as exc:
        log.error("tts.provider_not_implemented", provider=provider.name)
        await websocket.close(code=4501, reason=str(exc)[:120])
        return
    except Exception:
        log.exception("tts.stream_failed", gen_id=request.gen_id)
        await websocket.close(code=1011, reason="tts failure")
        return

    try:
        await websocket.close()
    except WebSocketDisconnect:
        # Клиент мог отменить поколение после последнего аудиочанка, но до
        # завершающего close-handshake. Это штатная гонка, не ошибка сервиса.
        return
