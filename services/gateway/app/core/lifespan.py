"""Жизненный цикл приложения: пулы соединений и реестр сессий.

Клиенты downstream-сервисов создаются один раз на процесс и живут в
`app.state`. Создавать httpx.AsyncClient на каждый запрос — значит платить
TCP-хендшейком в бюджете, где на весь ответ персонажа отведено 0.85-2.2 с (§9).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.clients.ai_client import AiClient
from app.clients.scenario_client import ScenarioClient
from app.clients.speech_client import SpeechClient
from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.engine import dispose_engine, init_engine, session_factory
from app.db.seed import seed_default_users
from app.orchestrator.session_manager import SessionRegistry

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()

    await init_engine()
    async with session_factory()() as db:
        await seed_default_users(db)

    app.state.sessions = SessionRegistry()
    app.state.ai = AiClient(settings.ai_service_url, settings.downstream_timeout_sec)
    app.state.speech = SpeechClient(settings.speech_service_url, settings.downstream_timeout_sec)
    app.state.scenario = ScenarioClient(
        settings.scenario_service_url, settings.downstream_timeout_sec
    )

    log.info(
        "gateway.started",
        speech=settings.speech_service_url,
        ai=settings.ai_service_url,
        scenario=settings.scenario_service_url,
    )

    try:
        yield
    finally:
        await app.state.ai.aclose()
        await app.state.speech.aclose()
        await app.state.scenario.aclose()
        await dispose_engine()
        log.info("gateway.stopped")
