"""Выбор провайдера LLM по конфигу."""

from app.core.config import Settings
from app.llm.base import LlmProvider
from app.llm.mock import MockLlmProvider


def create_llm_provider(
    settings: Settings,
    provider_name: str | None = None,
    base_url: str | None = None,
) -> LlmProvider:
    """`provider_name`/`base_url` перекрывают `settings.llm_provider` и эндпоинт
    провайдера по умолчанию — нужно генерации сценария (`SCENARIO_LLM_PROVIDER`/
    `SCENARIO_LLM_ENDPOINT`), у которой может быть свой провайдер и свой хост,
    отдельные от реплик персонажа и оценки. Ключ при этом берётся из того же
    поля `settings`, что и у основного провайдера: он привязан к провайдеру,
    а не к сценарию использования, и заводить под второй вызов отдельный ключ
    незачем.
    """
    var_name = "SCENARIO_LLM_PROVIDER" if provider_name else "LLM_PROVIDER"
    provider = (provider_name or settings.llm_provider).lower()

    match provider:
        case "mock":
            return MockLlmProvider()
        case "anthropic":
            if not settings.anthropic_api_key:
                raise ValueError(f"{var_name}=anthropic, но ANTHROPIC_API_KEY пуст")
            # Импорт внутри ветки: SDK тянется только когда он действительно нужен.
            from app.llm.anthropic_provider import AnthropicProvider

            return AnthropicProvider(
                api_key=settings.anthropic_api_key,
                base_url=base_url or settings.anthropic_base_url or None,
            )
        case "openai_compatible":
            if not settings.openai_compatible_api_key:
                raise ValueError(f"{var_name}=openai_compatible, но OPENAI_COMPATIBLE_API_KEY пуст")
            from app.llm.openai_compatible import OpenAiCompatibleProvider

            return OpenAiCompatibleProvider(
                api_key=settings.openai_compatible_api_key,
                base_url=base_url or settings.openai_compatible_base_url,
            )
        case _:
            raise ValueError(
                f"неизвестный {var_name}={(provider_name or settings.llm_provider)!r}; "
                "допустимо: mock | anthropic | openai_compatible"
            )
