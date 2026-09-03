"""Провайдер собирается верно по конфигу — без единого сетевого вызова.

Быстрая проверка перед Docker-пересборкой (см. docs/architecture.md): ловит
опечатки в именах, отсутствующие импорты и забытые проверки обязательных
ключей — до того, как это стоило бы цикла `docker compose build`.
"""

import pytest

from app.core.config import Settings
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.factory import create_llm_provider
from app.llm.mock import MockLlmProvider
from app.llm.openai_compatible import OpenAiCompatibleProvider


def test_mock_is_the_default_and_needs_no_keys() -> None:
    provider = create_llm_provider(Settings())
    assert isinstance(provider, MockLlmProvider)
    assert provider.name == "mock"


def test_anthropic_requires_api_key() -> None:
    settings = Settings(llm_provider="anthropic", anthropic_api_key="")
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        create_llm_provider(settings)


def test_anthropic_constructs_against_default_api_with_no_network_call() -> None:
    settings = Settings(llm_provider="anthropic", anthropic_api_key="test-key")
    provider = create_llm_provider(settings)
    assert isinstance(provider, AnthropicProvider)
    assert provider.name == "anthropic"


def test_anthropic_constructs_against_custom_gateway_base_url() -> None:
    """Прокси, отдающий настоящий Anthropic Messages API (не OpenAI-совместимый —
    для того есть openai_compatible), подключается через тот же провайдер, просто
    с другим base_url. Без /v1 на конце — SDK сам его дописывает."""
    settings = Settings(
        llm_provider="anthropic",
        anthropic_api_key="test-key",
        anthropic_base_url="https://router.cheap",
    )
    provider = create_llm_provider(settings)
    assert isinstance(provider, AnthropicProvider)


def test_openai_compatible_requires_api_key() -> None:
    settings = Settings(llm_provider="openai_compatible", openai_compatible_api_key="")
    with pytest.raises(ValueError, match="OPENAI_COMPATIBLE_API_KEY"):
        create_llm_provider(settings)


def test_openai_compatible_constructs_with_key_and_no_network_call() -> None:
    settings = Settings(
        llm_provider="openai_compatible",
        openai_compatible_api_key="test-key",
        openai_compatible_base_url="https://api.vsellm.ru/v1",
    )
    provider = create_llm_provider(settings)
    assert isinstance(provider, OpenAiCompatibleProvider)
    assert provider.name == "openai_compatible"


def test_unknown_provider_raises() -> None:
    settings = Settings(llm_provider="does-not-exist")
    with pytest.raises(ValueError, match="неизвестный LLM_PROVIDER"):
        create_llm_provider(settings)
