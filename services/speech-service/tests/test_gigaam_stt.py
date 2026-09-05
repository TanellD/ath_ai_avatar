from uuid import uuid4

import httpx

from app.stt.base import (
    EndpointObserved,
    FinalizationComplete,
    ProviderFault,
    RecognitionIdentity,
    SttSessionConfig,
)
from app.stt.gigaam import GigaAmSttProvider


def _config() -> SttSessionConfig:
    identity = RecognitionIdentity("session", uuid4(), 0, "gigaam")
    return SttSessionConfig(identity, "ru", "pcm_s16le", 16_000, 1)


async def test_gigaam_buffers_canonical_pcm_and_emits_one_final() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.content == b"\x01\x00\x02\x00"
        assert request.headers["X-Sample-Rate"] == "16000"
        return httpx.Response(200, json={"text": "  тестовая реплика  ", "inference_ms": 10})

    provider = GigaAmSttProvider(
        worker_url="http://worker",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    await provider.open(_config())
    await provider.push(b"\x01\x00")
    await provider.push(b"\x02\x00")
    await provider.finalize()
    events = [event async for event in provider.events()]

    assert isinstance(events[0], EndpointObserved)
    assert isinstance(events[1], FinalizationComplete)
    assert events[1].text == "тестовая реплика"
    assert events[1].confidence is None


async def test_gigaam_normalizes_worker_failure() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(503))
    provider = GigaAmSttProvider(
        worker_url="http://worker", timeout_seconds=1, transport=transport
    )
    await provider.open(_config())
    await provider.push(b"\x00\x00")
    await provider.finalize()
    events = [event async for event in provider.events()]

    assert len(events) == 1
    assert isinstance(events[0], ProviderFault)
    assert events[0].retryable is True
