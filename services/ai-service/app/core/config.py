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

    # Реплика персонажа короткая по сути жанра: он спрашивает и дожимает,
    # а не читает лекцию. Ограничение заодно бережёт бюджет латентности.
    character_max_tokens: int = 300
    character_temperature: float = 0.8

    # Оценка — детерминированная задача, разброс здесь только вредит.
    evaluation_max_tokens: int = 4000
    evaluation_temperature: float = 0.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
