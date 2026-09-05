"""Точка входа rag-service — база знаний сценария (issue #11)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, knowledge
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.knowledge.embeddings import EmbeddingsClient
from app.knowledge.store import KnowledgeStore

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.embeddings = EmbeddingsClient(
        base_url=settings.embeddings_base_url,
        api_key=settings.embeddings_api_key,
        model=settings.embeddings_model,
    )
    app.state.store = KnowledgeStore(settings.chroma_path)

    log.info("rag.started", embeddings_model=settings.embeddings_model)
    try:
        yield
    finally:
        await app.state.embeddings.aclose()
        log.info("rag.stopped")


def create_app() -> FastAPI:
    setup_logging()

    app = FastAPI(
        title="ATH RAG Service",
        description="База знаний сценария: чанкинг, эмбеддинги, ChromaDB (issue #11)",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Экран методиста (загрузка документа) обращается сюда напрямую из
    # браузера, как и к scenario-service — тот же паттерн (main.py рядом).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(knowledge.router)

    return app


app = create_app()
