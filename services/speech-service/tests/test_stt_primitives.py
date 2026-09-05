from uuid import uuid4

import pytest

from app.stt.base import (
    FinalizationComplete,
    ProviderCapabilities,
    RecognitionIdentity,
    SttSessionConfig,
)
from app.stt.capture_buffer import (
    CaptureBuffer,
    CaptureBufferLimitError,
    InvalidPcmFrameError,
)
from app.stt.mock import MockSttProvider


def test_capture_buffer_counts_pcm_samples_and_clears() -> None:
    buffer = CaptureBuffer(max_duration_seconds=1, max_frame_bytes=8)
    buffer.append(b"\x01\x00\x02\x00")

    assert buffer.samples == 2
    assert buffer.snapshot() == b"\x01\x00\x02\x00"

    buffer.clear()
    assert buffer.size_bytes == 0


def test_capture_buffer_rejects_partial_sample_and_limits() -> None:
    frame_limited = CaptureBuffer(max_duration_seconds=1, max_frame_bytes=4)

    with pytest.raises(InvalidPcmFrameError):
        frame_limited.append(b"\x00")
    with pytest.raises(CaptureBufferLimitError):
        frame_limited.append(b"\x00" * 6)

    duration_limited = CaptureBuffer(max_duration_seconds=1, max_frame_bytes=32_000)
    duration_limited.append(b"\x00\x00" * 16_000)
    with pytest.raises(CaptureBufferLimitError):
        duration_limited.append(b"\x00\x00")


@pytest.mark.asyncio
async def test_mock_provider_preserves_optional_metadata() -> None:
    identity = RecognitionIdentity("session", uuid4(), 0, "mock")
    final = FinalizationComplete(identity=identity, text="тест", confidence=None)
    capabilities = ProviderCapabilities(False, False, False, False, False, True)
    provider = MockSttProvider([final], capabilities=capabilities)
    config = SttSessionConfig(identity, "ru", "pcm_s16le", 16_000, 1)

    await provider.open(config)
    await provider.push(b"\x00\x00")
    await provider.finalize()
    events = [event async for event in provider.events()]

    assert events == [final]
    assert provider.capabilities.confidence is False
    assert provider.audio == b"\x00\x00"
