import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

from app.stt.base import (
    FinalizationComplete,
    NormalizedSttEvent,
    ProviderCapabilities,
    ProviderFault,
    ProviderFaultKind,
    ProviderSwitched,
    RecognitionIdentity,
    SttProvider,
    SttSessionConfig,
)
from app.stt.failover import FailoverSttProvider

# Реальный GigaAM отдаёт только финал; фейк повторяет это, иначе тест не увидит
# главного следствия failover — исчезновения партиалов.
FULL = ProviderCapabilities(True, True, True, True, True, True)
LOCAL_DEGRADED = ProviderCapabilities(False, False, False, False, False, True)


class ControlledProvider(SttProvider):
    def __init__(
        self,
        name: str,
        *,
        fault: bool = False,
        open_error: bool = False,
        capabilities: ProviderCapabilities = FULL,
    ) -> None:
        self._name = name
        self._fault = fault
        self._open_error = open_error
        self._capabilities = capabilities
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
        return self._capabilities

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
    fallback = ControlledProvider("gigaam", capabilities=LOCAL_DEGRADED)
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
    # Переключение объявляется отдельным событием и раньше финала: клиент должен
    # узнать об исчезновении партиалов, пока пользователь ещё говорит.
    assert [type(event) for event in events] == [ProviderSwitched, FinalizationComplete]
    assert events[0].capabilities.streaming_partials is False
    assert events[0].identity.provider_epoch == 1
    assert events[1].identity.provider == "gigaam"
    assert events[1].identity.provider_epoch == 1


async def test_primary_open_failure_selects_fallback_before_audio() -> None:
    primary = ControlledProvider("soniox", open_error=True)
    fallback = ControlledProvider("gigaam", capabilities=LOCAL_DEGRADED)
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
    assert isinstance(events[0], ProviderSwitched)
    assert isinstance(events[1], FinalizationComplete)
    assert events[1].identity.provider_epoch == 1


async def test_primary_finalize_stall_replays_to_fallback() -> None:
    primary = StalledProvider("soniox")
    fallback = ControlledProvider("gigaam", capabilities=LOCAL_DEGRADED)
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
    assert isinstance(events[0], ProviderSwitched)
    assert isinstance(events[1], FinalizationComplete)
    assert events[1].identity.provider_epoch == 1


class StalledThenLateFinalProvider(ControlledProvider):
    """Молчит на finalize, а финал присылает уже после того, как его заменили."""

    def __init__(self, name: str, **kwargs) -> None:
        super().__init__(name, **kwargs)
        self.emit_late = asyncio.Event()
        self.late_reached = False

    async def finalize(self) -> None:
        self.finalized.set()

    async def events(self) -> AsyncIterator[NormalizedSttEvent]:
        await self.emit_late.wait()
        assert self.config is not None
        # Флаг подтверждает, что опоздавший финал действительно был отдан
        # читателю: без него тест мог бы проходить, просто не дойдя сюда.
        self.late_reached = True
        yield FinalizationComplete(identity=self.config.identity, text="late soniox final")


class RaisingProvider(ControlledProvider):
    async def events(self) -> AsyncIterator[NormalizedSttEvent]:
        await self.release.wait()
        raise ConnectionError("socket died mid-turn")
        yield  # pragma: no cover - делает функцию генератором


class FinalThenDisconnectProvider(ControlledProvider):
    async def events(self) -> AsyncIterator[NormalizedSttEvent]:
        await self.release.wait()
        assert self.config is not None
        yield FinalizationComplete(identity=self.config.identity, text="soniox final")
        raise ConnectionError("socket closed right after the final")


async def _settle(times: int = 6) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


async def test_late_primary_final_after_failover_is_dropped() -> None:
    """Soniox отвечает уже после того, как его подменили: ход принадлежит GigaAM."""
    primary = StalledThenLateFinalProvider("soniox")
    fallback = ControlledProvider("gigaam", capabilities=LOCAL_DEGRADED)
    manager = FailoverSttProvider(
        primary_factory=lambda: primary,
        fallback_factory=lambda: fallback,
        max_audio_bytes=32_000,
        finalize_timeout_seconds=0.001,
    )
    await manager.open(_config())
    await manager.push(b"\x05\x00")
    await manager.finalize()
    await asyncio.sleep(0.01)
    assert fallback.config is not None, "watchdog обязан был переключить провайдера"

    # Ответ опоздавшего провайдера приходит, когда epoch уже сменился.
    primary.emit_late.set()
    await _settle()
    assert primary.late_reached is True, "опоздавший финал должен был дойти до читателя"

    events = [event async for event in manager.events()]

    texts = [event.text for event in events if isinstance(event, FinalizationComplete)]
    assert texts == ["fallback text"]


async def test_fallback_unavailable_ends_the_capture_for_text_input() -> None:
    """Локальный движок тоже недоступен: типизированная ошибка, а не зависание."""
    primary = ControlledProvider("soniox", fault=True)
    fallback = ControlledProvider("gigaam", open_error=True, capabilities=LOCAL_DEGRADED)
    manager = FailoverSttProvider(
        primary_factory=lambda: primary,
        fallback_factory=lambda: fallback,
        max_audio_bytes=32_000,
    )
    await manager.open(_config())
    await manager.push(b"\x06\x00")
    primary.release.set()
    events = [event async for event in manager.events()]

    assert len(events) == 1
    fault = events[0]
    assert isinstance(fault, ProviderFault)
    # Повторять некуда, поэтому retryable=False: gateway обязан отдать
    # пользователю текстовый ввод, а не ждать ещё одной попытки.
    assert fault.retryable is False
    assert "fallback_unavailable" in fault.message
    # Переключения не объявляем: партиалов не будет, но и провайдера нет.
    assert not any(isinstance(event, ProviderSwitched) for event in events)


async def test_fallback_fault_is_not_retried() -> None:
    """Для GigaAM повторного failover нет: второй раз падать некуда."""
    created: list[ControlledProvider] = []

    def fallback_factory() -> SttProvider:
        provider = ControlledProvider("gigaam", fault=True, capabilities=LOCAL_DEGRADED)
        created.append(provider)
        provider.release.set()
        return provider

    primary = ControlledProvider("soniox", fault=True)
    manager = FailoverSttProvider(
        primary_factory=lambda: primary,
        fallback_factory=fallback_factory,
        max_audio_bytes=32_000,
    )
    await manager.open(_config())
    await manager.push(b"\x07\x00")
    primary.release.set()
    events = [event async for event in manager.events()]

    assert len(created) == 1, "второй fallback означал бы бесконечную цепочку"
    assert [type(event) for event in events] == [ProviderSwitched, ProviderFault]


async def test_final_then_disconnect_keeps_the_final() -> None:
    """Обрыв сразу после финала не должен превращаться в потерю хода."""
    primary = FinalThenDisconnectProvider("soniox")
    fallback = ControlledProvider("gigaam", capabilities=LOCAL_DEGRADED)
    manager = FailoverSttProvider(
        primary_factory=lambda: primary,
        fallback_factory=lambda: fallback,
        max_audio_bytes=32_000,
    )
    await manager.open(_config())
    await manager.push(b"\x08\x00")
    await manager.finalize()
    events = [event async for event in manager.events()]

    assert [type(event) for event in events] == [FinalizationComplete]
    assert events[0].text == "soniox final"
    assert fallback.config is None, "failover после успешного финала не нужен"


async def test_disconnect_then_final_comes_from_the_fallback() -> None:
    """Обратный порядок: связь оборвалась раньше, чем пришёл финал."""
    primary = RaisingProvider("soniox")
    fallback = ControlledProvider("gigaam", capabilities=LOCAL_DEGRADED)
    manager = FailoverSttProvider(
        primary_factory=lambda: primary,
        fallback_factory=lambda: fallback,
        max_audio_bytes=32_000,
    )
    await manager.open(_config())
    await manager.push(b"\x09\x00")
    primary.release.set()
    await _settle()
    await manager.finalize()
    events = [event async for event in manager.events()]

    assert [type(event) for event in events] == [ProviderSwitched, FinalizationComplete]
    assert events[1].text == "fallback text"
    assert fallback.audio == b"\x09\x00", "буфер должен переиграться целиком"


async def test_recovery_happens_only_on_the_next_capture() -> None:
    """Soniox снова становится основным на новом capture, а не внутри старого."""
    primaries: list[ControlledProvider] = []
    fallbacks: list[ControlledProvider] = []

    def primary_factory() -> SttProvider:
        provider = ControlledProvider("soniox", fault=len(primaries) == 0)
        primaries.append(provider)
        return provider

    def fallback_factory() -> SttProvider:
        provider = ControlledProvider("gigaam", capabilities=LOCAL_DEGRADED)
        fallbacks.append(provider)
        return provider

    def build() -> FailoverSttProvider:
        return FailoverSttProvider(
            primary_factory=primary_factory,
            fallback_factory=fallback_factory,
            max_audio_bytes=32_000,
        )

    first = build()
    await first.open(_config())
    await first.push(b"\x0a\x00")
    primaries[0].release.set()
    await _settle()
    assert fallbacks and fallbacks[0].config is not None, "первый ход обязан был деградировать"

    # Новый capture — новый менеджер: деградация предыдущего хода не переносится.
    second = build()
    await second.open(_config())
    await second.push(b"\x0b\x00")
    await second.finalize()
    events = [event async for event in second.events()]

    assert len(primaries) == 2
    assert primaries[1].audio == b"\x0b\x00", "второй ход снова начинается с Soniox"
    assert not any(isinstance(event, ProviderSwitched) for event in events)
