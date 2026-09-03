"""Точка входа gateway — оркестратора тренировочной сессии (Claude.md §5)."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, health, sessions, ws
from app.core.config import get_settings
from app.core.lifespan import lifespan
from app.core.logging import setup_logging


def create_app() -> FastAPI:
    setup_logging()
    settings = get_settings()

    app = FastAPI(
        title="ATH Gateway",
        description="Оркестратор: WebSocket-сессия, gen_id, конечный автомат этапов",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(sessions.router)
    app.include_router(ws.router)
    app.include_router(admin.router)

    return app


app = create_app()
