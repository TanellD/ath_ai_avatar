"""База знаний сценария (RAG) — issue #11.

Осознанный выход за Claude.md §4 («допустим простейший поиск по короткому
документу») в сторону полноценной векторной БД с эмбеддингами (ChromaDB) —
решение зафиксировано в постановке задачи от 2026-09-05, не в коде задним
числом.

Документ живёт в scenario-service (владелец сценария), эмбеддинги — там же
через Ollama (`EMBEDDINGS_MODEL`, по умолчанию nomic-embed-text). gateway
запрашивает готовые фрагменты через `/scenarios/{id}/knowledge/query` и
передаёт их в ai-service как `knowledge_context` (см. api.py) — ai-service
про ChromaDB ничего не знает, получает уже готовый список строк.
"""

from pydantic import BaseModel, Field


class KnowledgeDocInfo(BaseModel):
    """Что методист видит про загруженный документ."""

    filename: str
    chunk_count: int
    uploaded_at: str


class KnowledgeUploadResponse(BaseModel):
    doc: KnowledgeDocInfo


class KnowledgeListResponse(BaseModel):
    items: list[KnowledgeDocInfo]


class KnowledgeQueryRequest(BaseModel):
    """Запрос релевантных фрагментов — вызывается gateway'ем, не браузером."""

    query: str
    top_k: int = Field(default=3, ge=1, le=10)


class KnowledgeQueryResponse(BaseModel):
    chunks: list[str] = Field(
        description="Только текст фрагментов, без метаданных — ai-service кладёт их прямо в промпт"
    )
