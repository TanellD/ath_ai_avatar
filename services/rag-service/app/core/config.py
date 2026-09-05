"""Конфигурация rag-service (issue #11)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "rag-service"
    log_level: str = "INFO"
    log_format: str = "json"

    # Эмбеддинги — тот же Ollama, что и LLM в ai-service (openai-совместимый
    # /v1/embeddings), но отдельная модель: nomic-embed-text вместо чат-модели.
    # EMBEDDINGS_API_KEY Ollama не проверяет — поле обязательно только по
    # форме OpenAI-клиента.
    embeddings_base_url: str = "http://127.0.0.1:11434/v1"
    embeddings_api_key: str = "ollama"
    embeddings_model: str = "nomic-embed-text"

    # Персистентное хранилище ChromaDB — bind-mount ./data, как у SQLite
    # остальных сервисов (docs/data.md), переживает docker compose down.
    chroma_path: str = "/data/chroma"

    # Параметры чанкинга — простое разбиение по абзацам с ограничением длины,
    # без семантического сплиттера: документ короткий (Claude.md §4 в
    # исходной постановке), усложнять сверх ChromaDB незачем.
    chunk_max_chars: int = 800
    chunk_overlap_chars: int = 120


@lru_cache
def get_settings() -> Settings:
    return Settings()
