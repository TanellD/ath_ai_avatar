import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

from app.stt.base import (
    FinalizationComplete,
    NormalizedSttEvent,
    ProviderCapabilities,
    ProviderFault,
    ProviderFaultKind,
    RecognitionIdentity,
    SttProvider,
    SttSessionConfig,
)
from app.stt.failover import FailoverSttProvider


class ControlledProvider(SttProvider):
    def __init__(self, name: str, *, fault: bool = False, open_error: bool = False) -> None:
        self._name = name
        self._fault = fault
        self._open_error = open_error
        self.config: SttSessionConfig | None = None
        self.audio = bytearray()
        self.release = asyncio.Event()
        self.finalized = asyncio.Event()
        self.closed = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(True, True, True, True, True, True)

    async def open(self, config: SttSessionConfig) -> None:
        if self._open_error:
            raise ConnectionError("injected open failure")
        self.config = config

    async def push(self, pcm: bytes) -> None:
        self.audio.extend(pcm)

    async def finalize(self) -> None:
        self.finalized.set()
        self.release.set()

    async def events(self) -> AsyncIterator[NormalizedSttEvent]:
        await self.release.wait()
        assert self.config is not None
        if self._fault:
            yield ProviderFault(
                identity=self.config.identity,
                kind=ProviderFaultKind.DISCONNECTED,
                retryable=True,
                message="injected fault",
            )
        else:
            yield FinalizationComplete(identity=self.config.identity, text="fallback text")

    async def aclose(self) -> None:
        self.closed = True


class StalledProvider(ControlledProvider):
    async def finalize(self) -> None:
        self.finalized.set()


def _config() -> SttSessionConfig:
    return SttSessionConfig(
        RecognitionIdentity("session", uuid4(), 0, "soniox"),
        "ru",
        "pcm_s16le",
        16_000,
        1,
    )


async def test_mid_turn_fault_replays_all_audio_and_increments_epoch() -> None:
    primary = ControlledProvider("soniox", fault=True)
    fallback = ControlledProvider("gigaam")
    manager = FailoverSttProvider(
        primary_factory=lambda: primary,
        fallback_factory=lambda: fallback,
        max_audio_bytes=32_000,
    )
    await manager.open(_config())
    await manager.push(b"\x01\x00\x02\x00")
    primary.release.set()

    for _ in range(100):
        if fallback.config is not None:
            break
        await asyncio.sleep(0)
    await manager.finalize()
    events = [event async for event in manager.events()]

    assert fallback.audio == b"\x01\x00\x02\x00"
    assert len(events) == 1
    assert isinstance(events[0], FinalizationComplete)
    assert events[0].identity.provider == "gigaam"
    assert events[0].identity.provider_epoch == 1


async def test_primary_open_failure_selects_fallback_before_audio() -> None:
    primary = ControlledProvider("soniox", open_error=True)
    fallback = ControlledProvider("gigaam")
    manager = FailoverSttProvider(
        primary_factory=lambda: primary,
        fallback_factory=lambda: fallback,
        max_audio_bytes=32_000,
    )
    await manager.open(_config())
    await manager.push(b"\x03\x00")
    await manager.finalize()
    events = [event async for event in manager.events()]

    assert primary.closed is True
    assert fallback.audio == b"\x03\x00"
    assert isinstance(events[0], FinalizationComplete)
    assert events[0].identity.provider_epoch == 1


async def test_primary_finalize_stall_replays_to_fallback() -> None:
    primary = StalledProvider("soniox")
    fallback = ControlledProvider("gigaam")
    manager = FailoverSttProvider(
        primary_factory=lambda: primary,
        fallback_factory=lambda: fallback,
        max_audio_bytes=32_000,
        finalize_timeout_seconds=0.001,
    )
    await manager.open(_config())
    await manager.push(b"\x04\x00")
    await manager.finalize()
    events = [event async for event in manager.events()]

    assert fallback.audio == b"\x04\x00"
    assert isinstance(events[0], FinalizationComplete)
    assert events[0].identity.provider_epoch == 1
