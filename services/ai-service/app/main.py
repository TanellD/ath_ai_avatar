"""Точка входа ai-service (Claude.md §5, §7)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import character, classify, evaluation, health
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.llm.factory import create_llm_provider

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.llm = create_llm_provider(settings)

    log.info(
        "ai.started",
        provider=app.state.llm.name,
        fast_model=settings.llm_fast_model,
        strong_model=settings.llm_strong_model,
    )
    try:
        yield
    finally:
        await app.state.llm.aclose()
        log.info("ai.stopped")


def create_app() -> FastAPI:
    setup_logging()

    app = FastAPI(
        title="ATH AI Service",
        description="Реплики персонажа, классификация ответа, итоговая оценка",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(health.router)
    app.include_router(character.router)
    app.include_router(classify.router)
    app.include_router(evaluation.router)

    return app


app = create_app()
