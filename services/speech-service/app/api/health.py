"""Health и readiness speech-service."""

from fastapi import APIRouter, Request, Response, status

from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": get_settings().service_name}


@router.get("/ready")
async def ready(request: Request, response: Response) -> dict[str, object]:
    """Провайдер создан и его конфиг валиден.

    Живую проверку у внешнего API здесь не делаем намеренно: /ready дёргается
    healthcheck'ом раз в десять секунд, и платить за это вызовом платного TTS
    не стоит.
    """
    provider = getattr(request.app.state, "tts", None)

    if provider is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "dependencies": {"tts": "fail: provider not initialised"}}

    return {"status": "ok", "dependencies": {"tts": f"ok ({provider.name})"}}
