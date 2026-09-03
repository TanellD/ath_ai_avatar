"""Health и readiness ai-service."""

from fastapi import APIRouter, Request, Response, status

from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": get_settings().service_name}


@router.get("/ready")
async def ready(request: Request, response: Response) -> dict[str, object]:
    """Провайдер создан. Пробного вызова модели не делаем: /ready дёргается
    healthcheck'ом постоянно, и платить за это токенами не стоит."""
    provider = getattr(request.app.state, "llm", None)

    if provider is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "dependencies": {"llm": "fail: provider not initialised"}}

    settings = get_settings()
    return {
        "status": "ok",
        "dependencies": {
            "llm": f"ok ({provider.name})",
            "fast_model": settings.llm_fast_model,
            "strong_model": settings.llm_strong_model,
        },
    }
