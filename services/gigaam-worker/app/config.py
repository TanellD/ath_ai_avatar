from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gigaam_model: str = "v3_e2e_ctc"
    gigaam_device: str = "cpu"
    gigaam_cache_dir: str = "/models/gigaam"
    gigaam_max_capture_seconds: int = 20
    gigaam_queue_size: int = 1


@lru_cache
def get_settings() -> Settings:
    return Settings()
