"""Клиент speech-service: потоковый TTS.

WebSocket, а не HTTP, потому что чанки должны идти по мере синтеза: TTS
озвучивает ответ по частям, пользователь не ждёт генерации целиком (§3).

Одиночный вызов используется лабораторией и recovery-аудио. Основной pipeline
держит один stream на всю реплику и отправляет в него предложения по мере
генерации LLM. При CancelledError соединение закрывается вместе с задачей.

[STT] В голосовой фазе здесь появится второе направление — стрим микрофонного
аудио в STT. См. docs/stt-phase.md.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress

import httpx
import websockets
from ath_contracts import Emotion
from ath_contracts.api import (
    SttOpenRequest,
    SttServiceEvent,
    TtsChunk,
    TtsRequest,
    TtsTextChunk,
    parse_stt_service_event,
)

from app.core.logging import get_logger

log = get_logger(__name__)


class SpeechClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._ws_url = self._base_url.replace("http://", "ws://").replace("https://", "wss://")
        self._http = httpx.AsyncClient(base_url=self._base_url, timeout=timeout)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def ping(self) -> None:
        """Для GET /ready."""
        response = await self._http.get("/health", timeout=3.0)
        response.raise_for_status()

    async def stream_tts(
        self,
        gen_id: int,
        seq: int,
        text: str,
        voice_id: str | None,
        emotion: Emotion = Emotion.NEUTRAL,
    ) -> AsyncIterator[TtsChunk]:
        """Озвучить одно предложение, отдавая чанки по мере готовности."""
        request = TtsRequest(
            gen_id=gen_id, seq=seq, text=text, voice_id=voice_id, emotion=emotion
        )

        async with websockets.connect(f"{self._ws_url}/tts/stream") as ws:
            await ws.send(request.model_dump_json())

            async for raw in ws:
                chunk = TtsChunk.model_validate(json.loads(raw))
                yield chunk

    async def stream_tts_reply(
        self,
        gen_id: int,
        seq: int,
        texts: AsyncIterator[str],
        voice_id: str | None,
        emotion: Emotion = Emotion.NEUTRAL,
    ) -> AsyncIterator[TtsChunk]:
        """Один непрерывный TTS stream на всю реплику персонажа."""
        async with websockets.connect(f"{self._ws_url}/tts/stream") as ws:
            await ws.send(
                TtsRequest(
                    gen_id=gen_id,
                    seq=seq,
                    text="",
                    text_end=False,
                    voice_id=voice_id,
                    emotion=emotion,
                ).model_dump_json()
            )

            async def send_text() -> None:
                try:
                    async for text in texts:
                        await ws.send(TtsTextChunk(text=text).model_dump_json())
                    await ws.send(TtsTextChunk(text="", text_end=True).model_dump_json())
                except Exception:
                    await ws.close()
                    raise

            sender = asyncio.create_task(send_text())
            try:
                async for raw in ws:
                    chunk = TtsChunk.model_validate(json.loads(raw))
                    yield chunk
                await sender
            finally:
                if not sender.done():
                    sender.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await sender

    async def open_stt(self, request: SttOpenRequest) -> "SttStream":
        ws = await websockets.connect(f"{self._ws_url}/stt/stream")
        await ws.send(request.model_dump_json())
        return SttStream(ws)


class SttStream:
    """Одна gateway → speech-service capture."""

    def __init__(self, websocket) -> None:  # noqa: ANN001
        self._ws = websocket

    async def push(self, pcm: bytes) -> None:
        await self._ws.send(pcm)

    async def finalize(self) -> None:
        await self._ws.send('{"type":"finalize"}')

    async def events(self) -> AsyncIterator[SttServiceEvent]:
        async for raw in self._ws:
            yield parse_stt_service_event(json.loads(raw))

    async def aclose(self) -> None:
        await self._ws.close()
