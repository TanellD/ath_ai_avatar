import asyncio
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.engine import load_engine

logger = logging.getLogger(__name__)


class TranscriptionResponse(BaseModel):
    text: str
    model: str
    inference_ms: int
    rss_mb: float | None


class InferenceQueueFullError(RuntimeError):
    pass


class InferenceGate:
    """One inference slot plus a small bounded waiting room."""

    def __init__(self, queue_size: int) -> None:
        self._limit = 1 + max(queue_size, 0)
        self._pending = 0
        self._semaphore = asyncio.Semaphore(1)

    async def run(self, function: Callable[..., Any], *args: Any) -> Any:
        if self._pending >= self._limit:
            raise InferenceQueueFullError("GigaAM inference queue is full")
        self._pending += 1
        try:
            async with self._semaphore:
                return await asyncio.to_thread(function, *args)
        finally:
            self._pending -= 1


def create_app(
    *,
    settings: Settings | None = None,
    engine_loader: Callable[[Settings], Any] = load_engine,
) -> FastAPI:
    config = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = None
        app.state.load_error = None
        app.state.gate = InferenceGate(config.gigaam_queue_size)

        async def preload() -> None:
            try:
                app.state.engine = await asyncio.to_thread(engine_loader, config)
                logger.info("GigaAM model is ready", extra={"model": config.gigaam_model})
            except Exception as exc:  # readiness exposes failure without killing liveness
                app.state.load_error = str(exc)
                logger.exception("GigaAM model preload failed")

        task = asyncio.create_task(preload())
        app.state.preload_task = task
        yield
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(title="GigaAM worker", lifespan=lifespan)

    @app.get("/health", status_code=status.HTTP_204_NO_CONTENT)
    async def health() -> Response:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/ready", status_code=status.HTTP_204_NO_CONTENT)
    async def ready(request: Request) -> Response:
        if request.app.state.engine is None:
            detail = "model preload failed" if request.app.state.load_error else "model is loading"
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/transcribe", response_model=TranscriptionResponse)
    async def transcribe(
        request: Request,
        audio_format: str = Header(alias="X-Audio-Format"),
        sample_rate: int = Header(alias="X-Sample-Rate"),
        channels: int = Header(alias="X-Audio-Channels"),
    ) -> TranscriptionResponse:
        if audio_format != "pcm_s16le" or sample_rate != 16_000 or channels != 1:
            raise HTTPException(status_code=415, detail="expected pcm_s16le, mono, 16000 Hz")
        pcm = await request.body()
        max_bytes = config.gigaam_max_capture_seconds * 16_000 * 2
        if not pcm or len(pcm) % 2:
            raise HTTPException(
                status_code=400,
                detail="PCM body must contain complete int16 samples",
            )
        if len(pcm) > max_bytes:
            raise HTTPException(status_code=413, detail="audio exceeds configured duration limit")
        engine = request.app.state.engine
        if engine is None:
            raise HTTPException(status_code=503, detail="model is not ready")

        started = perf_counter()
        try:
            result = await request.app.state.gate.run(engine.transcribe_pcm16, pcm)
        except InferenceQueueFullError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        inference_ms = round((perf_counter() - started) * 1000)
        return TranscriptionResponse(
            text=result.text,
            model=config.gigaam_model,
            inference_ms=inference_ms,
            rss_mb=_max_rss_mb(),
        )

    return app


app = create_app()


def _max_rss_mb() -> float | None:
    try:
        import resource
    except ImportError:  # pragma: no cover - worker image is Linux
        return None
    # Linux reports ru_maxrss in KiB.
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
