"""Конфигурация speech-service."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "speech-service"
    log_level: str = "INFO"
    log_format: str = "json"

    tts_provider: str = Field(
        default="mock", description="mock | elevenlabs | yandex | soniox — см. app/tts/factory.py"
    )
    tts_voice_id: str = ""
    tts_sample_rate: int = 24000

    # Кэш аудио для детерминированных фраз — прежде всего самопредставления
    # персонажа (docs/agent-initiative.md). В памяти процесса: сервис и так
    # однопроцессный, а холодный кэш после рестарта стоит один синтез.
    tts_cache_enabled: bool = True
    tts_cache_max_entries: int = 256

    elevenlabs_api_key: str = ""
    yandex_api_key: str = ""
    yandex_folder_id: str = ""

    # Единственный провайдер из четырёх, реально реализованный (§10) — выбор
    # провалидирован веткой poc. Голос "Nina" и русский язык — те же значения,
    # что подтвердили рабочий результат там.
    soniox_api_key: str = ""
    soniox_voice: str = "Nina"
    soniox_language: str = "ru"

    # ------------------------------------------------------------- [STT]
    # Голосовой ввод — следующая фаза. Поля объявлены, но не читаются ничем:
    # см. app/stt/README.md и docs/stt-phase.md.
    # stt_provider: str = "deepgram"
    # deepgram_api_key: str = ""
    # stt_language: str = "ru"


@lru_cache
def get_settings() -> Settings:
    return Settings()
