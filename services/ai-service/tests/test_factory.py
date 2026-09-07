"""Провайдер собирается верно по конфигу — без единого сетевого вызова.

Быстрая проверка перед Docker-пересборкой (см. docs/engineering/architecture.md): ловит
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
    assert Settings.model_fields["llm_provider"].default == "mock"
    provider = create_llm_provider(Settings(llm_provider="mock"))
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


# --------------------------------- SCENARIO_LLM_PROVIDER (генерация сценария)


def test_provider_name_overrides_llm_provider() -> None:
    """Методист держит в .env ключи сразу нескольких провайдеров — генерация
    сценария может пользоваться не тем же провайдером, что реплики персонажа
    и оценка."""
    settings = Settings(llm_provider="mock", openai_compatible_api_key="test-key")
    provider = create_llm_provider(settings, provider_name="openai_compatible")

    assert isinstance(provider, OpenAiCompatibleProvider)


def test_missing_key_for_overridden_provider_names_the_scenario_var() -> None:
    """Ошибка обязана указывать на SCENARIO_LLM_PROVIDER, а не на LLM_PROVIDER
    — иначе методист будет чинить не ту переменную."""
    settings = Settings(llm_provider="mock", anthropic_api_key="")
    with pytest.raises(ValueError, match=r"SCENARIO_LLM_PROVIDER=anthropic.*ANTHROPIC_API_KEY"):
        create_llm_provider(settings, provider_name="anthropic")


def test_unknown_overridden_provider_names_the_scenario_var() -> None:
    settings = Settings(llm_provider="mock")
    with pytest.raises(ValueError, match="неизвестный SCENARIO_LLM_PROVIDER"):
        create_llm_provider(settings, provider_name="does-not-exist")


# ---------------------------- SCENARIO_LLM_ENDPOINT (свой хост провайдера)


def test_base_url_override_reaches_the_anthropic_client() -> None:
    """SCENARIO_LLM_ENDPOINT — свой хост под генерацию сценария, отдельно от
    ANTHROPIC_BASE_URL, которым пользуются реплики персонажа и оценка."""
    settings = Settings(anthropic_api_key="test-key", anthropic_base_url="https://main.proxy")
    provider = create_llm_provider(
        settings, provider_name="anthropic", base_url="https://scenario.proxy"
    )

    assert str(provider._client.base_url).rstrip("/") == "https://scenario.proxy"


def test_base_url_override_reaches_the_openai_compatible_client() -> None:
    settings = Settings(
        openai_compatible_api_key="test-key",
        openai_compatible_base_url="https://main.proxy/v1",
    )
    provider = create_llm_provider(
        settings, provider_name="openai_compatible", base_url="https://scenario.proxy/v1"
    )

    assert str(provider._client.base_url).rstrip("/") == "https://scenario.proxy/v1"


def test_no_base_url_override_keeps_the_provider_default() -> None:
    """Основной провайдер (без provider_name/base_url) не должен видеть
    SCENARIO_LLM_ENDPOINT — только вызывающий с явным override."""
    settings = Settings(
        llm_provider="anthropic",
        anthropic_api_key="test-key",
        anthropic_base_url="https://main.proxy",
    )
    provider = create_llm_provider(settings)

    assert "main.proxy" in str(provider._client.base_url)


# ------------------------- SCENARIO_LLM_API_KEY (свой ключ провайдера)


def test_api_key_override_reaches_the_client() -> None:
    """SCENARIO_LLM_API_KEY — свой аккаунт/лимит под генерацию сценария,
    отдельно от ANTHROPIC_API_KEY основного провайдера."""
    settings = Settings(anthropic_api_key="main-key")
    provider = create_llm_provider(settings, provider_name="anthropic", api_key="scenario-key")

    assert provider._client.api_key == "scenario-key"


def test_missing_api_key_falls_back_to_the_main_one() -> None:
    """Отдельный ключ не обязателен — методисту может хватать того же
    аккаунта, что у основного провайдера."""
    settings = Settings(anthropic_api_key="main-key")
    provider = create_llm_provider(settings, provider_name="anthropic")

    assert provider._client.api_key == "main-key"
