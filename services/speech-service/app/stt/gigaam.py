"""Buffered STT adapter for the internal local GigaAM worker."""

import asyncio
from collections.abc import AsyncIterator

import httpx

from app.stt.base import (
    EndpointKind,
    EndpointObserved,
    FinalizationComplete,
    NormalizedSttEvent,
    ProviderCapabilities,
    ProviderFault,
    ProviderFaultKind,
    SttProvider,
    SttSessionConfig,
)


class GigaAmSttProvider(SttProvider):
    def __init__(
        self,
        *,
        worker_url: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._worker_url = worker_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._config: SttSessionConfig | None = None
        self._audio = bytearray()
        self._result: FinalizationComplete | ProviderFault | None = None
        self._finalized = asyncio.Event()
        self._closed = False

    @property
    def name(self) -> str:
        return "gigaam"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(False, False, False, False, False, True)

    async def open(self, config: SttSessionConfig) -> None:
        if config.audio_format != "pcm_s16le" or config.sample_rate != 16_000:
            raise ValueError("GigaAM STT expects canonical pcm_s16le at 16 kHz")
        if config.num_channels != 1:
            raise ValueError("GigaAM STT expects mono audio")
        self._config = config

    async def push(self, pcm: bytes) -> None:
        if self._config is None or self._closed:
            raise RuntimeError("STT provider is not open")
        self._audio.extend(pcm)

    async def finalize(self) -> None:
        if self._config is None or self._closed:
            raise RuntimeError("STT provider is not open")
        identity = self._config.identity
        headers = {
            "X-Audio-Format": self._config.audio_format,
            "X-Sample-Rate": str(self._config.sample_rate),
            "X-Audio-Channels": str(self._config.num_channels),
            "Content-Type": "application/octet-stream",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    f"{self._worker_url}/transcribe",
                    content=bytes(self._audio),
                    headers=headers,
                )
                response.raise_for_status()
                text = str(response.json().get("text") or "").strip()
            self._result = FinalizationComplete(identity=identity, text=text)
        except httpx.HTTPStatusError as exc:
            self._result = ProviderFault(
                identity=identity,
                kind=(
                    ProviderFaultKind.RATE_LIMIT
                    if exc.response.status_code == 429
                    else ProviderFaultKind.INTERNAL
                ),
                retryable=exc.response.status_code in {429, 503},
                message=f"GigaAM worker returned HTTP {exc.response.status_code}",
            )
        except (httpx.HTTPError, ValueError) as exc:
            self._result = ProviderFault(
                identity=identity,
                kind=ProviderFaultKind.CONNECT,
                retryable=True,
                message=f"GigaAM worker unavailable: {type(exc).__name__}",
            )
        finally:
            self._finalized.set()

    async def events(self) -> AsyncIterator[NormalizedSttEvent]:
        await self._finalized.wait()
        if self._config is None or self._result is None:
            return
        if isinstance(self._result, FinalizationComplete):
            yield EndpointObserved(self._config.identity, EndpointKind.MANUAL)
        yield self._result

    async def aclose(self) -> None:
        self._closed = True
        self._audio.clear()
