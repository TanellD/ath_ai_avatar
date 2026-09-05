import asyncio
from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@dataclass(frozen=True)
class FakeResult:
    text: str


class FakeEngine:
    def transcribe_pcm16(self, pcm: bytes) -> FakeResult:
        return FakeResult(text=f"samples:{len(pcm) // 2}")


def _client(**overrides) -> TestClient:
    settings = Settings(gigaam_max_capture_seconds=1, **overrides)
    app = create_app(settings=settings, engine_loader=lambda _: FakeEngine())
    return TestClient(app)


def test_health_readiness_and_transcription() -> None:
    with _client() as client:
        for _ in range(50):
            if client.get("/ready").status_code == 204:
                break
        response = client.post(
            "/transcribe",
            content=b"\x00\x00" * 160,
            headers={
                "X-Audio-Format": "pcm_s16le",
                "X-Sample-Rate": "16000",
                "X-Audio-Channels": "1",
            },
        )

    assert response.status_code == 200
    assert response.json()["text"] == "samples:160"
    assert response.json()["model"] == "v3_e2e_ctc"


def test_rejects_invalid_audio_and_oversize_body() -> None:
    headers = {
        "X-Audio-Format": "pcm_s16le",
        "X-Sample-Rate": "16000",
        "X-Audio-Channels": "1",
    }
    with _client() as client:
        response = client.post("/transcribe", content=b"\x00", headers=headers)
        oversized = client.post("/transcribe", content=b"\x00\x00" * 16001, headers=headers)

    assert response.status_code == 400
    assert oversized.status_code == 413


def test_reports_not_ready_without_exposing_loader_error() -> None:
    def broken_loader(_: Settings):
        raise RuntimeError("private filesystem detail")

    app = create_app(settings=Settings(), engine_loader=broken_loader)
    with TestClient(app) as client:
        for _ in range(50):
            response = client.get("/ready")
            if response.json().get("detail") == "model preload failed":
                break
            asyncio.run(asyncio.sleep(0))

    assert response.status_code == 503
    assert response.json() == {"detail": "model preload failed"}
