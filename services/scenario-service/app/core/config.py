"""Конфигурация scenario-service."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "scenario-service"
    log_level: str = "INFO"
    log_format: str = "json"

    database_url: str = "sqlite+aiosqlite:////data/scenarios.db"

    # Засеять встроенные шаблоны при старте, если их ещё нет в БД.
    # Демо начинается с «методист выбирает шаблон» (§11), поэтому пустая база
    # на чистом клоне — это сломанный первый шаг демо.
    seed_templates: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
