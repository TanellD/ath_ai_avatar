"""Provider-neutral realtime STT WebSocket for the gateway."""

import asyncio
import json

from ath_contracts.api import (
    SttEndpointEvent,
    SttFaultEvent,
    SttFinalEvent,
    SttOpenRequest,
    SttProgressEvent,
    SttTranscriptEvent,
)
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.core.config import get_settings
from app.stt.base import (
    EndpointObserved,
    FinalizationComplete,
    ProviderFault,
    RecognitionIdentity,
    RecognitionProgress,
    SttSessionConfig,
    TranscriptHypothesis,
)
from app.stt.capture_buffer import CaptureBuffer, CaptureBufferLimitError, InvalidPcmFrameError
from app.stt.factory import create_stt_provider

router = APIRouter()


@router.websocket("/stt/stream")
async def stt_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    provider = None
    buffer = None
    event_task: asyncio.Task[None] | None = None
    finalized = False

    try:
        try:
            request = SttOpenRequest.model_validate(await websocket.receive_json())
        except (ValidationError, ValueError) as exc:
            await websocket.close(code=4400, reason=f"invalid STT open request: {exc}")
            return

        settings = get_settings()
        provider = create_stt_provider(settings)
        identity = RecognitionIdentity(
            session_id=request.session_id,
            capture_id=request.capture_id,
            provider_epoch=request.provider_epoch,
            provider=provider.name,
        )
        config = SttSessionConfig(
            identity=identity,
            language=request.language,
            audio_format=request.audio_format,
            sample_rate=request.sample_rate,
            num_channels=request.num_channels,
            context_terms=tuple(request.context_terms),
        )
        buffer = CaptureBuffer(
            max_duration_seconds=settings.voice_max_capture_seconds,
            max_frame_bytes=settings.voice_max_frame_bytes,
        )
        await provider.open(config)
        event_task = asyncio.create_task(_relay_events(websocket, provider))

        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            frame = message.get("bytes")
            if frame is not None:
                try:
                    buffer.append(frame)
                except (CaptureBufferLimitError, InvalidPcmFrameError) as exc:
                    await websocket.close(code=4400, reason=str(exc))
                    break
                await provider.push(frame)
                continue

            text = message.get("text")
            try:
                control = json.loads(text) if text is not None else None
            except json.JSONDecodeError:
                control = None
            if control == {"type": "finalize"}:
                await provider.finalize()
                finalized = True
                break
            await websocket.close(code=4400, reason="expected binary PCM or finalize")
            break

        if finalized and event_task is not None:
            await event_task
    except WebSocketDisconnect:
        pass
    finally:
        if event_task is not None and not event_task.done():
            event_task.cancel()
            await asyncio.gather(event_task, return_exceptions=True)
        if provider is not None:
            await provider.aclose()
        if buffer is not None:
            buffer.clear()


async def _relay_events(websocket: WebSocket, provider) -> None:  # noqa: ANN001
    async for event in provider.events():
        identity = event.identity
        common = {
            "capture_id": identity.capture_id,
            "provider_epoch": identity.provider_epoch,
            "provider": identity.provider,
        }
        if isinstance(event, RecognitionProgress):
            outgoing = SttProgressEvent(
                **common, audio_samples_processed=event.audio_samples_processed
            )
        elif isinstance(event, TranscriptHypothesis):
            outgoing = SttTranscriptEvent(
                **common, text=event.text, confidence=event.confidence
            )
        elif isinstance(event, EndpointObserved):
            outgoing = SttEndpointEvent(**common, kind=event.kind.value)
        elif isinstance(event, FinalizationComplete):
            outgoing = SttFinalEvent(
                **common, text=event.text, confidence=event.confidence
            )
        elif isinstance(event, ProviderFault):
            outgoing = SttFaultEvent(
                **common,
                kind=event.kind.value,
                retryable=event.retryable,
                message=event.message,
                provider_request_id=event.provider_request_id,
            )
        else:
            continue
        await websocket.send_json(outgoing.model_dump(mode="json"))
