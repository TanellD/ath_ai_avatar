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
    # провалидирован веткой poc.
    soniox_api_key: str = ""
    # Голос по умолчанию, когда его не задали ни аватар, ни персона.
    # Reese — единственный русский голос, проверенный на реальном синтезе
    # (см. докстринг app/tts/soniox.py). Список доступных: `make voices`.
    soniox_voice: str = "Reese"
    soniox_language: str = "ru"

    # ------------------------------------------------------------- STT
    stt_provider: str = Field(
        default="mock", description="mock | soniox | gigaam | soniox_gigaam"
    )
    stt_language: str = "ru"
    soniox_stt_model: str = "stt-rt-v5"
    soniox_stt_websocket_url: str = "wss://stt-rt.soniox.com/transcribe-websocket"
    gigaam_worker_url: str = "http://gigaam-worker:8020"
    gigaam_timeout_seconds: float = 60.0
    stt_finalize_timeout_seconds: float = 5.0

    # Управляемые сбои основного STT: нужны, чтобы проверить и показать
    # failover, не дожидаясь настоящего отказа сети. Выключено по умолчанию —
    # эндпоинт не появляется вовсе, пока флаг не поднят явно.
    stt_debug_faults_enabled: bool = False

    # Safety limits are deliberately conservative dev defaults. Product values
    # are pinned only after our own benchmark (docs/voice-input-plan.md).
    voice_max_capture_seconds: int = 20
    voice_max_frame_bytes: int = 32_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
