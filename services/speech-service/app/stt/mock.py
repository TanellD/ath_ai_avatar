"""Детерминированный STT provider для contract/failover тестов."""

import asyncio
from collections.abc import AsyncIterator, Iterable

from app.stt.base import (
    FinalizationComplete,
    NormalizedSttEvent,
    ProviderCapabilities,
    SttProvider,
    SttSessionConfig,
)


class MockSttProvider(SttProvider):
    def __init__(
        self,
        scripted_events: Iterable[NormalizedSttEvent] = (),
        *,
        capabilities: ProviderCapabilities | None = None,
    ) -> None:
        self._scripted_events = tuple(scripted_events)
        self._capabilities = capabilities or ProviderCapabilities(
            streaming_partials=True,
            confidence=True,
            token_timestamps=True,
            semantic_endpoint=True,
            context_terms=True,
            manual_finalize=True,
        )
        self.config: SttSessionConfig | None = None
        self.audio = bytearray()
        self.finalized = False
        self.closed = False
        self._finalized_event = asyncio.Event()

    @property
    def name(self) -> str:
        return "mock"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def open(self, config: SttSessionConfig) -> None:
        self.config = config

    async def push(self, pcm: bytes) -> None:
        if self.config is None or self.closed:
            raise RuntimeError("STT provider is not open")
        self.audio.extend(pcm)

    async def finalize(self) -> None:
        if self.config is None or self.closed:
            raise RuntimeError("STT provider is not open")
        self.finalized = True
        self._finalized_event.set()

    async def events(self) -> AsyncIterator[NormalizedSttEvent]:
        await self._finalized_event.wait()
        if not self._scripted_events and self.config is not None:
            yield FinalizationComplete(identity=self.config.identity, text="")
            return
        for event in self._scripted_events:
            yield event

    async def aclose(self) -> None:
        self.closed = True
