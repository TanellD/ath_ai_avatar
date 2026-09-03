"""Health и readiness.

Разделение осмысленное, а не ритуальное: /health отвечает «процесс жив» и им
пользуется docker healthcheck, /ready проверяет реальные зависимости и им
пользуется человек, когда что-то не работает. Смешивать их нельзя — иначе
временная недоступность ai-service перезапустит здоровый gateway.
"""

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from app.core.config import get_settings
from app.db.engine import session_factory

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": get_settings().service_name}


@router.get("/ready")
async def ready(request: Request, response: Response) -> dict[str, object]:
    dependencies: dict[str, str] = {}

    try:
        async with session_factory()() as db:
            await db.execute(text("SELECT 1"))
        dependencies["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 — в ответ уходит текст причины
        dependencies["database"] = f"fail: {exc}"

    for name, client in (
        ("speech-service", request.app.state.speech),
        ("ai-service", request.app.state.ai),
        ("scenario-service", request.app.state.scenario),
    ):
        try:
            await client.ping()
            dependencies[name] = "ok"
        except Exception as exc:  # noqa: BLE001
            dependencies[name] = f"fail: {exc}"

    ok = all(value == "ok" for value in dependencies.values())
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"status": "ok" if ok else "degraded", "dependencies": dependencies}
