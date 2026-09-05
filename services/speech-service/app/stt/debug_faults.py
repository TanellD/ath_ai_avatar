"""Управляемые сбои основного провайдера — только для dev и демонстрации.

Failover нельзя ни проверить руками, ни показать, если Soniox нечем сломать:
ждать настоящего сбоя сети посреди защиты — не план. Обёртка живёт отдельным
файлом и включается только флагом, поэтому в рабочем пути её нет вовсе:
внутри `soniox.py` не появляется ни одной отладочной ветки.

Взводится на одну capture: показали деградацию — следующий ход снова обычный.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum

from app.core.logging import get_logger
from app.stt.base import (
    NormalizedSttEvent,
    ProviderCapabilities,
    ProviderFault,
    ProviderFaultKind,
    SttProvider,
    SttSessionConfig,
)

log = get_logger(__name__)


class FaultMode(StrEnum):
    OFF = "off"
    OPEN = "open"
    """Провайдер не поднимается — failover до первого байта аудио."""
    MIDTURN = "midturn"
    """Обрыв посреди речи: буфер переигрывается в GigaAM."""
    STALL = "stall"
    """Соединение живо, но финал не приходит — работа finalize-watchdog'а."""


@dataclass
class FaultSwitch:
    """Взведённый сбой. Одна на процесс, состояние живёт до срабатывания."""

    mode: FaultMode = FaultMode.OFF
    captures: int = 0

    def arm(self, mode: FaultMode, captures: int) -> None:
        self.mode = mode
        self.captures = max(0, captures)
        log.warning("stt.debug_fault_armed", mode=mode.value, captures=self.captures)

    def take(self) -> FaultMode:
        """Забрать режим для очередной capture и списать одно срабатывание."""
        if self.mode is FaultMode.OFF or self.captures <= 0:
            return FaultMode.OFF
        self.captures -= 1
        if self.captures == 0:
            mode, self.mode = self.mode, FaultMode.OFF
            return mode
        return self.mode


_switch = FaultSwitch()


def get_switch() -> FaultSwitch:
    return _switch


class FaultInjectingProvider(SttProvider):
    """Оборачивает настоящий провайдер и ломает его заданным способом."""

    def __init__(self, inner: SttProvider, mode: FaultMode, *, frames_before_fault: int) -> None:
        self._inner = inner
        self._mode = mode
        self._frames_before_fault = frames_before_fault
        self._frames = 0
        self._config: SttSessionConfig | None = None
        self._injected: asyncio.Queue[ProviderFault] = asyncio.Queue()

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._inner.capabilities

    async def open(self, config: SttSessionConfig) -> None:
        self._config = config
        if self._mode is FaultMode.OPEN:
            log.warning("stt.debug_fault_fired", mode=self._mode.value, stage="open")
            raise ConnectionError("debug fault: primary refused to open")
        await self._inner.open(config)

    async def push(self, pcm: bytes) -> None:
        await self._inner.push(pcm)
        if self._mode is not FaultMode.MIDTURN:
            return
        self._frames += 1
        if self._frames == self._frames_before_fault:
            assert self._config is not None
            log.warning("stt.debug_fault_fired", mode=self._mode.value, stage="push")
            await self._injected.put(
                ProviderFault(
                    identity=self._config.identity,
                    kind=ProviderFaultKind.DISCONNECTED,
                    retryable=True,
                    message="debug fault: primary dropped mid-turn",
                )
            )

    async def finalize(self) -> None:
        if self._mode is FaultMode.STALL:
            # Молчим намеренно: именно так выглядит «сокет жив, финала нет».
            log.warning("stt.debug_fault_fired", mode=self._mode.value, stage="finalize")
            return
        await self._inner.finalize()

    async def events(self) -> AsyncIterator[NormalizedSttEvent]:
        if self._mode is FaultMode.MIDTURN:
            yield await self._injected.get()
            return
        if self._mode is FaultMode.STALL:
            await asyncio.Event().wait()  # pragma: no cover - снимается отменой
        async for event in self._inner.events():
            yield event

    async def aclose(self) -> None:
        await self._inner.aclose()
