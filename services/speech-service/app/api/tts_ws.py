"""WebSocket синтеза — Claude.md §3, §10.

Протокол: клиент (gateway) присылает один `TtsRequest`, сервис отвечает
потоком `TtsChunk` и закрывает соединение после чанка с `is_final=True`.

Одно соединение на предложение, а не на сессию. Так отмена поколения — это
просто закрытие сокета со стороны gateway, и внутри протокола не нужен
отдельный кадр «отмена». Меньше состояний — меньше способов уронить метрику 4.

`gen_id` сервис не интерпретирует: он только возвращает его в каждом чанке,
чтобы gateway мог отфильтровать хвост, не сопоставляя ответы по порядку.
"""

import base64
import json

from ath_contracts.api import TtsChunk, TtsRequest
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
    try:
        async for chunk in provider.synthesize(request.text, request.voice_id):
            payload = TtsChunk(
                gen_id=request.gen_id,
                seq=seq,
                data=base64.b64encode(chunk.data).decode("ascii"),
                format="wav",
                sample_rate=chunk.sample_rate,
                is_final=chunk.is_final,
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

    await websocket.close()
