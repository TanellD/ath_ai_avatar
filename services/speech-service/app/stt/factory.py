"""STT provider selection is centralized here."""

from app.core.config import Settings
from app.stt.base import SttProvider
from app.stt.debug_faults import FaultInjectingProvider, FaultMode, get_switch
from app.stt.failover import FailoverSttProvider
from app.stt.gigaam import GigaAmSttProvider
from app.stt.mock import MockSttProvider
from app.stt.soniox import SonioxSttProvider


def create_stt_provider(settings: Settings) -> SttProvider:
    name = settings.stt_provider.lower()
    if name == "soniox_gigaam":
        return FailoverSttProvider(
            primary_factory=lambda: _wrap_debug_fault(
                _create_named_provider("soniox", settings), settings
            ),
            fallback_factory=lambda: _create_named_provider("gigaam", settings),
            max_audio_bytes=settings.voice_max_capture_seconds * 16_000 * 2,
            finalize_timeout_seconds=settings.stt_finalize_timeout_seconds,
        )
    return _create_named_provider(name, settings)


def _create_named_provider(name: str, settings: Settings) -> SttProvider:
    if name == "mock":
        return MockSttProvider()
    if name == "soniox":
        return SonioxSttProvider(
            api_key=settings.soniox_api_key,
            model=settings.soniox_stt_model,
            websocket_url=settings.soniox_stt_websocket_url,
        )
    if name == "gigaam":
        return GigaAmSttProvider(
            worker_url=settings.gigaam_worker_url,
            timeout_seconds=settings.gigaam_timeout_seconds,
        )
    raise ValueError(f"Unknown STT_PROVIDER: {name}")


def _wrap_debug_fault(provider: SttProvider, settings: Settings) -> SttProvider:
    """Подмешать управляемый сбой, если он взведён и разрешён конфигом.

    Режим снимается со взвода здесь, в одной точке создания провайдера: так
    сбой гарантированно приходится ровно на одну capture.
    """
    if not settings.stt_debug_faults_enabled:
        return provider
    mode = get_switch().take()
    if mode is FaultMode.OFF:
        return provider
    return FaultInjectingProvider(provider, mode, frames_before_fault=10)
