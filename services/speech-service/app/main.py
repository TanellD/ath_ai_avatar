"""Точка входа speech-service (Claude.md §10)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health, stt_ws, tts_ws
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.tts.factory import create_tts_provider

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.tts = create_tts_provider(settings)

    log.info("speech.started", tts_provider=app.state.tts.name)
    try:
        yield
    finally:
        await app.state.tts.aclose()
        log.info("speech.stopped")


def create_app() -> FastAPI:
    setup_logging()

    app = FastAPI(
        title="ATH Speech Service",
        description="Потоковые TTS и STT.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(health.router)
    app.include_router(tts_ws.router)
    app.include_router(stt_ws.router)

    # Управляемые сбои STT существуют только в dev-конфигурации: в обычной
    # эти пути не «запрещены», а отсутствуют.
    if get_settings().stt_debug_faults_enabled:
        from app.api import debug_stt

        app.include_router(debug_stt.router)
        log.warning("speech.debug_faults_enabled")

    return app


app = create_app()
