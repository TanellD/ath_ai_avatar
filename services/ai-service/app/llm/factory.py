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

            return AnthropicProvider(api_key=settings.anthropic_api_key)
        case _:
            raise ValueError(
                f"неизвестный LLM_PROVIDER={settings.llm_provider!r}; допустимо: mock | anthropic"
            )
