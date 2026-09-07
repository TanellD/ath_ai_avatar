"""Провайдер собирается верно по конфигу — без единого сетевого вызова.

Быстрая проверка перед Docker-пересборкой (см. docs/engineering/architecture.md): ловит
опечатки в именах, отсутствующие импорты и забытые проверки обязательных
ключей — до того, как это стоило бы цикла `docker compose build`.
"""

import pytest

from app.core.config import Settings
from app.stt.factory import create_stt_provider
from app.stt.gigaam import GigaAmSttProvider
from app.tts.cache import CachingTtsProvider
from app.tts.factory import UnknownProviderError, create_tts_provider
from app.tts.mock import MockTtsProvider
from app.tts.soniox import SonioxTtsProvider


def test_mock_is_the_default_and_needs_no_keys() -> None:
    assert Settings.model_fields["tts_provider"].default == "mock"
    # Explicit value keeps construction deterministic under a developer's environment.
    provider = create_tts_provider(Settings(tts_provider="mock", tts_cache_enabled=False))
    assert isinstance(provider, MockTtsProvider)
    assert provider.name == "mock"


def test_soniox_requires_api_key() -> None:
    settings = Settings(tts_provider="soniox", soniox_api_key="")
    with pytest.raises(ValueError, match="SONIOX_API_KEY"):
        create_tts_provider(settings)


def test_soniox_constructs_with_key_and_no_network_call() -> None:
    """Конструктор SDK не должен стучаться в сеть — иначе этот тест невозможен
    без ключа."""
    settings = Settings(
        tts_provider="soniox",
        soniox_api_key="test-key",
        soniox_voice="Nina",
        soniox_language="ru",
        tts_sample_rate=24000,
        tts_cache_enabled=False,
    )
    provider = create_tts_provider(settings)
    assert isinstance(provider, SonioxTtsProvider)
    assert provider.name == "soniox"


def test_unknown_provider_raises() -> None:
    settings = Settings(tts_provider="does-not-exist")
    with pytest.raises(UnknownProviderError):
        create_tts_provider(settings)


def test_gigaam_stt_constructs_without_external_credentials() -> None:
    provider = create_stt_provider(Settings(stt_provider="gigaam"))
    assert isinstance(provider, GigaAmSttProvider)
    assert provider.name == "gigaam"
    assert provider.capabilities.streaming_partials is False


def test_cache_wraps_provider_by_default() -> None:
    """Кэш включён по умолчанию и не подменяет собой выбор провайдера."""
    provider = create_tts_provider(Settings(tts_provider="mock"))
    assert isinstance(provider, CachingTtsProvider)
    assert provider.name == "cached:mock"
