"""Точка входа ai-service (Claude.md §5, §7)."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import character, classify, evaluation, health
from app.core.config import Settings, get_settings
from app.core.logging import get_logger, setup_logging
from app.llm.factory import create_llm_provider
from app.llm.openai_compatible import OpenAiCompatibleProvider

log = get_logger(__name__)


async def _keep_warm_loop(provider: OpenAiCompatibleProvider, settings: Settings) -> None:
    """См. Settings.llm_keep_warm_* и OpenAiCompatibleProvider.keep_warm."""
    models = [settings.llm_fast_model, settings.llm_strong_model]
    while True:
        await provider.keep_warm(models, keep_alive=settings.llm_keep_warm_ttl)
        await asyncio.sleep(settings.llm_keep_warm_interval_sec)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.llm = create_llm_provider(settings)

    keep_warm_task: asyncio.Task[None] | None = None
    if settings.llm_keep_warm_enabled and isinstance(app.state.llm, OpenAiCompatibleProvider):
        keep_warm_task = asyncio.create_task(_keep_warm_loop(app.state.llm, settings))

    log.info(
        "ai.started",
        provider=app.state.llm.name,
        fast_model=settings.llm_fast_model,
        strong_model=settings.llm_strong_model,
        keep_warm=keep_warm_task is not None,
    )
    try:
        yield
    finally:
        if keep_warm_task is not None:
            keep_warm_task.cancel()
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
