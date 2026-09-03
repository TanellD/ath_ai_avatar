"""Health и readiness scenario-service."""

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.config import get_settings
from app.db.engine import session_factory

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": get_settings().service_name}


@router.get("/ready")
async def ready(response: Response) -> dict[str, object]:
    try:
        async with session_factory()() as db:
            await db.execute(text("SELECT 1"))
        return {"status": "ok", "dependencies": {"database": "ok"}}
    except Exception as exc:  # noqa: BLE001
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "dependencies": {"database": f"fail: {exc}"}}
