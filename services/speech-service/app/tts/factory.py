"""Выбор провайдера TTS по конфигу.

Единственное место, где имя провайдера превращается в объект. В референсном
проекте выбор транскрайбера размазан по обработчику upgrade с хардкодом
хостов внутри классов — здесь так не делаем.
"""

from app.core.config import Settings
from app.core.logging import get_logger
from app.tts.base import TtsProvider
from app.tts.cache import CachingTtsProvider
from app.tts.elevenlabs import ElevenLabsTtsProvider
from app.tts.mock import MockTtsProvider
from app.tts.soniox import SonioxTtsProvider
from app.tts.yandex import YandexTtsProvider

log = get_logger(__name__)


class UnknownProviderError(ValueError):
    pass


def create_tts_provider(settings: Settings) -> TtsProvider:
    """Провайдер по конфигу, при включённом кэше — обёрнутый в него.

    Кэш снаружи, а не внутри провайдеров: он одинаково полезен всем и не
    должен дублироваться в каждом (см. app/tts/cache.py).
    """
    provider = _create_raw_provider(settings)
    if settings.tts_cache_enabled:
        return CachingTtsProvider(provider, max_entries=settings.tts_cache_max_entries)
    return provider


def _create_raw_provider(settings: Settings) -> TtsProvider:
    provider = settings.tts_provider.lower()

    match provider:
        case "mock":
            return MockTtsProvider(sample_rate=settings.tts_sample_rate)
        case "elevenlabs":
            if not settings.elevenlabs_api_key:
                raise ValueError("TTS_PROVIDER=elevenlabs, но ELEVENLABS_API_KEY пуст")
            return ElevenLabsTtsProvider(
                api_key=settings.elevenlabs_api_key,
                default_voice_id=settings.tts_voice_id,
                sample_rate=settings.tts_sample_rate,
            )
        case "yandex":
            if not settings.yandex_api_key:
                raise ValueError("TTS_PROVIDER=yandex, но YANDEX_API_KEY пуст")
            return YandexTtsProvider(
                api_key=settings.yandex_api_key,
                folder_id=settings.yandex_folder_id,
                default_voice_id=settings.tts_voice_id,
                sample_rate=settings.tts_sample_rate,
            )
        case "soniox":
            if not settings.soniox_api_key:
                raise ValueError("TTS_PROVIDER=soniox, но SONIOX_API_KEY пуст")
            return SonioxTtsProvider(
                api_key=settings.soniox_api_key,
                default_voice=settings.soniox_voice,
                language=settings.soniox_language,
                sample_rate=settings.tts_sample_rate,
            )
        case _:
            raise UnknownProviderError(
                f"неизвестный TTS_PROVIDER={settings.tts_provider!r}; "
                "допустимо: mock | elevenlabs | yandex | soniox"
            )
