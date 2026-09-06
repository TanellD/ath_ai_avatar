"""Резолюция SCENARIO_LLM_* — Claude.md §5, §7.

Генерация сценария может жить на своём провайдере/модели/хосте, отдельно от
реплик персонажа и оценки. Пустая переменная должна прозрачно наследовать
основную — иначе включение фичи потребовало бы продублировать весь LLM_*
блок в .env даже тем, кому не нужен отдельный провайдер.
"""

from app.core.config import Settings


def test_scenario_provider_falls_back_to_the_main_one_when_unset() -> None:
    settings = Settings(llm_provider="anthropic")
    assert settings.effective_scenario_provider == "anthropic"


def test_scenario_provider_can_be_overridden() -> None:
    settings = Settings(llm_provider="anthropic", scenario_llm_provider="openai_compatible")
    assert settings.effective_scenario_provider == "openai_compatible"


def test_scenario_model_falls_back_to_the_strong_one_when_unset() -> None:
    """Одна модель на все три ручки (draft/rubric/details) — не быстрая/сильная
    пара, как у реплик персонажа и оценки: кнопки жмутся редко и вручную."""
    settings = Settings(llm_strong_model="opus", llm_fast_model="haiku")
    assert settings.effective_scenario_model == "opus"


def test_scenario_model_can_be_overridden() -> None:
    """У openai_compatible и anthropic разный словарь имён моделей: имя модели
    основного провайдера может быть невалидным для провайдера сценария."""
    settings = Settings(llm_strong_model="opus", scenario_llm_model="google/gemini-2.5-flash")
    assert settings.effective_scenario_model == "google/gemini-2.5-flash"


def test_scenario_endpoint_is_empty_by_default() -> None:
    """Пусто — factory берёт эндпоинт провайдера по умолчанию
    (ANTHROPIC_BASE_URL/OPENAI_COMPATIBLE_BASE_URL), а не отдельный хост."""
    settings = Settings()
    assert settings.effective_scenario_endpoint == ""


def test_scenario_endpoint_can_be_overridden() -> None:
    settings = Settings(scenario_llm_endpoint="https://scenario-proxy.internal/v1")
    assert settings.effective_scenario_endpoint == "https://scenario-proxy.internal/v1"
