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

    llm_provider: str = Field(default="mock", description="mock | anthropic")
    llm_fast_model: str = "claude-haiku-4-5"
    llm_strong_model: str = "claude-opus-5"

    anthropic_api_key: str = ""

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
