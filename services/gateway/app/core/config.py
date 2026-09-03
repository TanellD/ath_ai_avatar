"""Конфигурация gateway.

Все переменные окружения читаются здесь и только здесь, с валидацией. В
референсном проекте `process.env.X || 'default'` разбросан по пятнадцати
файлам, а один из них ещё и печатает весь environment в лог при старте —
повторять не будем.
"""

from functools import cached_property, lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "gateway"
    log_level: str = "INFO"
    log_format: str = Field(default="json", description="json | console")

    database_url: str = "sqlite+aiosqlite:////data/gateway.db"

    speech_service_url: str = "http://speech-service:8010"
    ai_service_url: str = "http://ai-service:8030"
    scenario_service_url: str = "http://scenario-service:8050"

    # Строка, а не list[str], намеренно: pydantic-settings разбирает поля
    # составных типов из переменных окружения как JSON, ДО валидаторов. Список
    # в env пришлось бы писать как '["http://..."]', что нечитаемо в .env и
    # роняет сервис при первой же запятой не на месте.
    cors_origins: str = "http://localhost:5173"

    # §5: полный текст последних N ходов + сжатая выжимка остального.
    # Без окна стоимость диалога растёт квадратично.
    max_context_turns: int = 6

    # Страховка от бесконечной сессии; сценарий обычно короче.
    max_session_turns: int = 60

    # Таймаут одного вызова downstream-сервиса. Держим коротким: бюджет
    # ответа персонажа целиком — 0.85-2.2 с (§9).
    downstream_timeout_sec: float = 30.0

    @cached_property
    def cors_origin_list(self) -> list[str]:
        """Разбор CORS_ORIGINS: значения через запятую."""
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
