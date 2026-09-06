"""Выбор провайдера LLM по конфигу."""

from app.core.config import Settings
from app.llm.base import LlmProvider
from app.llm.mock import MockLlmProvider


def create_llm_provider(
    settings: Settings,
    provider_name: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> LlmProvider:
    """`provider_name`/`base_url`/`api_key` перекрывают провайдера, хост и ключ
    по умолчанию — нужно генерации сценария (`SCENARIO_LLM_PROVIDER`/
    `SCENARIO_LLM_ENDPOINT`/`SCENARIO_LLM_API_KEY`), у которой может быть свой
    провайдер, свой хост и свой ключ, отдельные от реплик персонажа и оценки.
    Ключ, в отличие от `base_url`, необязательно свой: если методисту хватает
    того же аккаунта/лимита, что и у основного провайдера, `api_key` можно не
    задавать — тогда берётся ключ из обычных полей `settings`
    (`anthropic_api_key`/`openai_compatible_api_key`).
    """
    var_name = "SCENARIO_LLM_PROVIDER" if provider_name else "LLM_PROVIDER"
    # Только у сценария есть второй способ задать ключ — реплики персонажа и
    # оценка всегда берут его из ANTHROPIC_API_KEY/OPENAI_COMPATIBLE_API_KEY.
    key_hint = " или SCENARIO_LLM_API_KEY" if provider_name else ""
    provider = (provider_name or settings.llm_provider).lower()

    match provider:
        case "mock":
            return MockLlmProvider()
        case "anthropic":
            resolved_key = api_key or settings.anthropic_api_key
            if not resolved_key:
                raise ValueError(f"{var_name}=anthropic, но ANTHROPIC_API_KEY{key_hint} пуст")
            # Импорт внутри ветки: SDK тянется только когда он действительно нужен.
            from app.llm.anthropic_provider import AnthropicProvider

            return AnthropicProvider(
                api_key=resolved_key,
                base_url=base_url or settings.anthropic_base_url or None,
            )
        case "openai_compatible":
            resolved_key = api_key or settings.openai_compatible_api_key
            if not resolved_key:
                raise ValueError(
                    f"{var_name}=openai_compatible, но OPENAI_COMPATIBLE_API_KEY{key_hint} пуст"
                )
            from app.llm.openai_compatible import OpenAiCompatibleProvider

            return OpenAiCompatibleProvider(
                api_key=resolved_key,
                base_url=base_url or settings.openai_compatible_base_url,
            )
        case _:
            raise ValueError(
                f"неизвестный {var_name}={(provider_name or settings.llm_provider)!r}; "
                "допустимо: mock | anthropic | openai_compatible"
            )
