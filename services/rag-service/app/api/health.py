"""Health и readiness rag-service."""

from fastapi import APIRouter, Request, Response, status

from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": get_settings().service_name}


@router.get("/ready")
async def ready(request: Request, response: Response) -> dict[str, object]:
    """Хранилище ChromaDB открыто. Живой вызов Ollama-эмбеддингов сюда не
    кладём — тот же принцип, что у speech-service: /ready дёргается
    healthcheck'ом часто, платить за это сетевым вызовом не стоит."""
    store = getattr(request.app.state, "store", None)

    if store is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "dependencies": {"chroma": "fail: store not initialised"}}

    return {"status": "ok", "dependencies": {"chroma": "ok"}}
