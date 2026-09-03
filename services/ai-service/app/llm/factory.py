"""Выбор провайдера LLM по конфигу."""

from app.core.config import Settings
from app.llm.base import LlmProvider
from app.llm.mock import MockLlmProvider


def create_llm_provider(settings: Settings) -> LlmProvider:
    provider = settings.llm_provider.lower()

    match provider:
        case "mock":
            return MockLlmProvider()
        case "anthropic":
            if not settings.anthropic_api_key:
                raise ValueError("LLM_PROVIDER=anthropic, но ANTHROPIC_API_KEY пуст")
            # Импорт внутри ветки: SDK тянется только когда он действительно нужен.
            from app.llm.anthropic_provider import AnthropicProvider

            return AnthropicProvider(
                api_key=settings.anthropic_api_key,
                base_url=settings.anthropic_base_url or None,
            )
        case "openai_compatible":
            if not settings.openai_compatible_api_key:
                raise ValueError(
                    "LLM_PROVIDER=openai_compatible, но OPENAI_COMPATIBLE_API_KEY пуст"
                )
            from app.llm.openai_compatible import OpenAiCompatibleProvider

            return OpenAiCompatibleProvider(
                api_key=settings.openai_compatible_api_key,
                base_url=settings.openai_compatible_base_url,
            )
        case _:
            raise ValueError(
                f"неизвестный LLM_PROVIDER={settings.llm_provider!r}; "
                "допустимо: mock | anthropic | openai_compatible"
            )
