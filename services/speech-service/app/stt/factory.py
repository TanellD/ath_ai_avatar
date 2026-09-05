"""STT provider selection is centralized here."""

from app.core.config import Settings
from app.stt.base import SttProvider
from app.stt.mock import MockSttProvider
from app.stt.soniox import SonioxSttProvider


def create_stt_provider(settings: Settings) -> SttProvider:
    name = settings.stt_provider.lower()
    if name == "mock":
        return MockSttProvider()
    if name == "soniox":
        return SonioxSttProvider(
            api_key=settings.soniox_api_key,
            model=settings.soniox_stt_model,
            websocket_url=settings.soniox_stt_websocket_url,
        )
    raise ValueError(f"Unknown STT_PROVIDER: {settings.stt_provider}")
