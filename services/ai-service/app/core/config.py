"""Конфигурация ai-service.

Разделение моделей — из Claude.md §5, и оно не косметическое:

  - **быстрая** модель отвечает за реплики персонажа. Приоритет — time to first
    token; ум не важен, глубоких бесед в тренировке нет;
  - **сильная** модель вызывается один раз, после завершения сессии, и выдаёт
    структурированный JSON отчёта с обязательной цитатой под каждым баллом.

Смешать их в одну — значит либо платить за медленные реплики, либо получить
отчёт, которому нельзя верить.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "ai-service"
    log_level: str = "INFO"
    log_format: str = "json"

    llm_provider: str = Field(default="mock", description="mock | anthropic | openai_compatible")
    llm_fast_model: str = "claude-haiku-4-5"
    llm_strong_model: str = "claude-opus-5"

    anthropic_api_key: str = ""
    # Пусто = настоящий api.anthropic.com (дефолт самого SDK). Заполняется
    # только если ключ и биллинг идут через прокси/шлюз, отдающий тот же
    # реальный Anthropic Messages API (не OpenAI-совместимый — для этого
    # есть openai_compatible ниже). Без /v1 на конце: сам SDK дописывает
    # /v1/messages, так же как для api.anthropic.com.
    anthropic_base_url: str = ""

    # Второй провайдер (§10, по итогам ветки poc): VseLLM — OpenAI-совместимый
    # прокси. LLM_FAST_MODEL/LLM_STRONG_MODEL при этом провайдере должны
    # содержать имя модели прокси, например "google/gemini-2.5-flash", а не
    # имя модели Anthropic.
    openai_compatible_base_url: str = "https://api.vsellm.ru/v1"
    openai_compatible_api_key: str = ""

    scenario_llm_provider: str = Field(
        default="",
        description="Пусто — берёт LLM_PROVIDER. Свой провайдер для кнопок "
        "«Заполнить/Пересобрать сценарий по описанию» и «Заполнить критерии» "
        "в редакторе сценария, независимо от провайдера реплик персонажа и оценки",
    )
    """Ключи провайдеров (anthropic_api_key/openai_compatible_api_key выше) можно
    переиспользовать: методист держит в `.env` сразу несколько, эта переменная
    лишь выбирает, каким из уже настроенных провайдеров пользуется генерация
    сценария. Если же для сценария нужен именно ДРУГОЙ ключ того же
    провайдера (свой аккаунт/лимит/биллинг) — см. `scenario_llm_api_key` ниже."""

    scenario_llm_api_key: str = ""
    """Пусто — использует ключ основного провайдера (anthropic_api_key или
    openai_compatible_api_key, смотря какой провайдер выбран для сценария).

    Задаётся отдельно, когда у генерации сценария должен быть свой ключ —
    отдельный биллинг/лимит/аккаунт, а не только другой провайдер или хост.
    """

    scenario_llm_model: str = ""
    """Пусто — берёт LLM_STRONG_MODEL. Одна модель на все три ручки
    (`/scenario/draft`, `/scenario/rubric`, `/scenario/details`) — в отличие
    от реплик персонажа и оценки, здесь нет причины разделять быструю и
    сильную: кнопки жмутся редко, вручную, и не в бюджете задержки диалога.

    Обязательна, если SCENARIO_LLM_PROVIDER отличается от LLM_PROVIDER: у
    openai_compatible и anthropic разный словарь имён моделей, и унаследованное
    имя модели основного провайдера может быть невалидным для провайдера
    сценария.
    """

    scenario_llm_endpoint: str = ""
    """Пусто — использует общий эндпоинт провайдера (ANTHROPIC_BASE_URL или
    OPENAI_COMPATIBLE_BASE_URL, смотря какой провайдер выбран для сценария).

    Задаётся отдельно, когда генерация сценария должна идти на другой хост
    того же провайдера — например, свой прокси для тяжёлых редких вызовов,
    отдельный от того, что держит реплики персонажа под нагрузкой диалога.
    """

    # Реплика персонажа короткая по сути жанра: он спрашивает и дожимает,
    # а не читает лекцию. Ограничение заодно бережёт бюджет латентности.
    character_max_tokens: int = 300
    character_temperature: float = 0.8

    # Оценка — детерминированная задача, разброс здесь только вредит.
    evaluation_max_tokens: int = 4000
    evaluation_temperature: float = 0.0

    @property
    def effective_scenario_provider(self) -> str:
        return self.scenario_llm_provider or self.llm_provider

    @property
    def effective_scenario_model(self) -> str:
        return self.scenario_llm_model or self.llm_strong_model

    @property
    def effective_scenario_endpoint(self) -> str:
        """Пусто значит «эндпоинт провайдера по умолчанию» — вызывающий код
        (`llm/factory.py`) сам решает, в какое поле settings это разворачивать."""
        return self.scenario_llm_endpoint

    @property
    def effective_scenario_api_key(self) -> str:
        """Пусто значит «ключ провайдера по умолчанию» — тот же смысл, что у
        `effective_scenario_endpoint`, только для учётных данных."""
        return self.scenario_llm_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
