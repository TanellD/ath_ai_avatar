"""Per-capture Soniox primary -> local GigaAM fallback manager."""

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import replace

from app.core.logging import get_logger
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

log = get_logger(__name__)
_END = object()


class FailoverSttProvider(SttProvider):
    """Keeps lossless PCM until the capture is committed or aborted."""

    def __init__(
        self,
        *,
        primary_factory: Callable[[], SttProvider],
        fallback_factory: Callable[[], SttProvider],
        max_audio_bytes: int,
        finalize_timeout_seconds: float = 5.0,
    ) -> None:
        self._primary_factory = primary_factory
        self._fallback_factory = fallback_factory
        self._max_audio_bytes = max_audio_bytes
        self._finalize_timeout_seconds = finalize_timeout_seconds
        self._config: SttSessionConfig | None = None
        self._active: SttProvider | None = None
        self._using_fallback = False
        self._audio = bytearray()
        self._events: asyncio.Queue[NormalizedSttEvent | object] = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._reader_task: asyncio.Task[None] | None = None
        self._finalize_watchdog_task: asyncio.Task[None] | None = None
        self._finalize_requested = False
        self._closed = False
        self._terminal = False

    @property
    def name(self) -> str:
        return "soniox"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._primary_factory().capabilities

    async def open(self, config: SttSessionConfig) -> None:
        self._config = config
        primary = self._primary_factory()
        try:
            await primary.open(self._provider_config(primary, config.identity.provider_epoch))
            self._active = primary
            self._start_reader(primary)
        except Exception as exc:  # noqa: BLE001 - provider boundary
            await primary.aclose()
            log.warning("stt.primary_open_failed", error_type=type(exc).__name__)
            async with self._lock:
                await self._switch_locked("primary_open_failed")

    async def push(self, pcm: bytes) -> None:
        async with self._lock:
            if self._closed or self._active is None:
                raise RuntimeError("STT provider is not open")
            if len(self._audio) + len(pcm) > self._max_audio_bytes:
                raise ValueError("failover replay buffer limit exceeded")
            self._audio.extend(pcm)
            try:
                await self._active.push(pcm)
            except Exception as exc:  # noqa: BLE001 - provider boundary
                if self._using_fallback:
                    await self._emit_terminal_fault_locked("fallback_push_failed", exc)
                else:
                    await self._switch_locked("primary_push_failed")

    async def finalize(self) -> None:
        async with self._lock:
            if self._closed or self._active is None:
                raise RuntimeError("STT provider is not open")
            self._finalize_requested = True
            try:
                provider = self._active
                await provider.finalize()
                self._start_finalize_watchdog(provider)
            except Exception as exc:  # noqa: BLE001 - provider boundary
                if self._using_fallback:
                    await self._emit_terminal_fault_locked("fallback_finalize_failed", exc)
                else:
                    await self._switch_locked("primary_finalize_failed")

    async def events(self) -> AsyncIterator[NormalizedSttEvent]:
        while True:
            event = await self._events.get()
            if event is _END:
                return
            yield event  # type: ignore[misc]

    async def aclose(self) -> None:
        async with self._lock:
            self._closed = True
            if self._reader_task is not None and self._reader_task is not asyncio.current_task():
                self._reader_task.cancel()
            self._cancel_finalize_watchdog()
            if self._active is not None:
                await self._active.aclose()
            self._audio[:] = b"\x00" * len(self._audio)
            self._audio.clear()

    def _provider_config(self, provider: SttProvider, epoch: int) -> SttSessionConfig:
        assert self._config is not None
        identity = replace(self._config.identity, provider=provider.name, provider_epoch=epoch)
        return replace(self._config, identity=identity)

    def _start_reader(self, provider: SttProvider) -> None:
        self._reader_task = asyncio.create_task(self._read_provider(provider))

    async def _read_provider(self, provider: SttProvider) -> None:
        terminal_seen = False
        try:
            async for event in provider.events():
                async with self._lock:
                    if self._closed or self._active is not provider:
                        return
                    if isinstance(event, ProviderFault):
                        terminal_seen = True
                        if not self._using_fallback:
                            await self._switch_locked(f"primary_{event.kind.value}")
                        else:
                            await self._emit_event_terminal_locked(event)
                        return
                    await self._events.put(event)
                    if isinstance(event, FinalizationComplete):
                        self._cancel_finalize_watchdog()
                        terminal_seen = True
                        self._terminal = True
                        await self._events.put(_END)
                        return
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001 - provider boundary
            async with self._lock:
                if self._active is provider and not self._closed:
                    if self._using_fallback:
                        await self._emit_terminal_fault_locked("fallback_disconnected", exc)
                    else:
                        await self._switch_locked("primary_disconnected")
            return

        if not terminal_seen:
            async with self._lock:
                if self._active is provider and not self._closed:
                    if self._using_fallback:
                        await self._emit_terminal_fault_locked("fallback_disconnected")
                    else:
                        await self._switch_locked("primary_disconnected")

    async def _switch_locked(self, reason: str) -> None:
        if self._terminal or self._using_fallback or self._config is None:
            return
        old = self._active
        self._cancel_finalize_watchdog()
        self._using_fallback = True
        next_epoch = self._config.identity.provider_epoch + 1
        fallback = self._fallback_factory()
        try:
            if old is not None:
                await old.aclose()
            await fallback.open(self._provider_config(fallback, next_epoch))
            self._active = fallback
            if self._audio:
                await fallback.push(bytes(self._audio))
            if self._finalize_requested:
                await fallback.finalize()
                self._start_finalize_watchdog(fallback)
            self._start_reader(fallback)
            log.warning(
                "stt.failover_completed",
                reason=reason,
                provider_epoch=next_epoch,
                replay_bytes=len(self._audio),
            )
        except Exception as exc:  # noqa: BLE001 - provider boundary
            self._active = fallback
            await self._emit_terminal_fault_locked("fallback_unavailable", exc)

    async def _emit_terminal_fault_locked(
        self, message: str, exc: Exception | None = None
    ) -> None:
        assert self._config is not None
        provider = self._active.name if self._active is not None else "gigaam"
        epoch = self._config.identity.provider_epoch + int(self._using_fallback)
        identity = RecognitionIdentity(
            session_id=self._config.identity.session_id,
            capture_id=self._config.identity.capture_id,
            provider_epoch=epoch,
            provider=provider,
        )
        fault = ProviderFault(
            identity=identity,
            kind=ProviderFaultKind.DISCONNECTED,
            retryable=False,
            message=f"{message}: {type(exc).__name__}" if exc else message,
        )
        await self._emit_event_terminal_locked(fault)

    async def _emit_event_terminal_locked(self, event: ProviderFault) -> None:
        if self._terminal:
            return
        self._terminal = True
        self._cancel_finalize_watchdog()
        await self._events.put(event)
        await self._events.put(_END)

    def _start_finalize_watchdog(self, provider: SttProvider) -> None:
        self._cancel_finalize_watchdog()
        self._finalize_watchdog_task = asyncio.create_task(
            self._watch_finalize(provider)
        )

    def _cancel_finalize_watchdog(self) -> None:
        task = self._finalize_watchdog_task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        self._finalize_watchdog_task = None

    async def _watch_finalize(self, provider: SttProvider) -> None:
        try:
            await asyncio.sleep(self._finalize_timeout_seconds)
            async with self._lock:
                if self._active is not provider or self._terminal or self._closed:
                    return
                if self._using_fallback:
                    assert self._config is not None
                    identity = self._provider_config(provider, self._config.identity.provider_epoch + 1).identity
                    await self._emit_event_terminal_locked(
                        ProviderFault(
                            identity=identity,
                            kind=ProviderFaultKind.STALLED,
                            retryable=False,
                            message="GigaAM finalization timed out",
                        )
                    )
                else:
                    await self._switch_locked("primary_finalize_stalled")
        except asyncio.CancelledError:
            return
