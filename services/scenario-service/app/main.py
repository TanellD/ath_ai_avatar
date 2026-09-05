"""Точка входа scenario-service (Claude.md §2, §7)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import avatars, health, scenarios
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.db.engine import dispose_engine, init_engine
from app.seed.loader import seed_templates

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    await init_engine()

    if settings.seed_templates:
        await seed_templates()

    log.info("scenario.started")
    try:
        yield
    finally:
        await dispose_engine()
        log.info("scenario.stopped")


def create_app() -> FastAPI:
    setup_logging()

    app = FastAPI(
        title="ATH Scenario Service",
        description="Сценарии, шаблоны и рубрики методиста",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Экран методиста обращается сюда напрямую из браузера, минуя gateway:
    # оркестратору нечего добавить к обычному CRUD.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(scenarios.router)
    app.include_router(avatars.router)

    return app


app = create_app()
