"""Управляемые сбои: взвод на одну capture и невмешательство в рабочий путь."""

from app.core.config import Settings
from app.stt.debug_faults import FaultInjectingProvider, FaultMode, FaultSwitch
from app.stt.factory import _wrap_debug_fault, create_stt_provider
from app.stt.failover import FailoverSttProvider
from app.stt.mock import MockSttProvider


def test_switch_fires_once_and_disarms() -> None:
    switch = FaultSwitch()
    switch.arm(FaultMode.MIDTURN, captures=1)

    assert switch.take() is FaultMode.MIDTURN
    # Показали деградацию — следующий ход снова обычный.
    assert switch.take() is FaultMode.OFF
    assert switch.mode is FaultMode.OFF


def test_switch_can_cover_several_captures() -> None:
    switch = FaultSwitch()
    switch.arm(FaultMode.STALL, captures=2)

    assert switch.take() is FaultMode.STALL
    assert switch.take() is FaultMode.STALL
    assert switch.take() is FaultMode.OFF


def test_disarmed_switch_never_fires() -> None:
    assert FaultSwitch().take() is FaultMode.OFF


def test_wrapper_is_absent_unless_explicitly_enabled() -> None:
    from app.stt.debug_faults import get_switch

    get_switch().arm(FaultMode.MIDTURN, captures=1)
    inner = MockSttProvider()
    try:
        # Флаг выключен: обёртки нет, даже если сбой кто-то взвёл.
        assert _wrap_debug_fault(inner, Settings()) is inner
    finally:
        get_switch().arm(FaultMode.OFF, captures=0)


def test_wrapper_applies_when_enabled_and_armed() -> None:
    from app.stt.debug_faults import get_switch

    settings = Settings(stt_debug_faults_enabled=True)
    get_switch().arm(FaultMode.OPEN, captures=1)
    try:
        wrapped = _wrap_debug_fault(MockSttProvider(), settings)
        assert isinstance(wrapped, FaultInjectingProvider)
        # Имя и возможности остаются провайдерскими: failover не должен
        # различать подделку и настоящий движок.
        assert wrapped.name == MockSttProvider().name
    finally:
        get_switch().arm(FaultMode.OFF, captures=0)


def test_production_factory_is_untouched() -> None:
    provider = create_stt_provider(Settings(stt_provider="soniox_gigaam", soniox_api_key="x"))
    assert isinstance(provider, FailoverSttProvider)
