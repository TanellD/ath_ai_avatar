import asyncio
from uuid import uuid4

from ath_contracts import SpeechStart
from ath_contracts.api import SttFinalEvent, SttTranscriptEvent

from app.orchestrator.voice_turns import VoiceTurnRegistry


class FakePipeline:
    def __init__(self) -> None:
        self.finals: list[dict] = []

    async def begin_user_turn(self, _interrupts: int | None) -> int:
        return 1

    async def handle_voice_final(self, **kwargs) -> bool:
        self.finals.append(kwargs)
        return True


class FakeStream:
    def __init__(self) -> None:
        self.finalize_count = 0
        self.closed = False
        self.frames: list[bytes] = []
        self.queue: asyncio.Queue = asyncio.Queue()

    async def push(self, frame: bytes) -> None:
        self.frames.append(frame)

    async def finalize(self) -> None:
        self.finalize_count += 1

    async def events(self):
        while True:
            event = await self.queue.get()
            if event is None:
                return
            yield event

    async def aclose(self) -> None:
        self.closed = True


class FakeSpeech:
    def __init__(self, stream: FakeStream) -> None:
        self.stream = stream

    async def open_stt(self, _request):  # noqa: ANN001
        return self.stream


def make_registry(*, max_seconds: float = 20) -> tuple:
    pipeline = FakePipeline()
    stream = FakeStream()
    sent = []

    async def send(event) -> None:  # noqa: ANN001
        sent.append(event)

    registry = VoiceTurnRegistry(
        session_id="session",
        pipeline=pipeline,
        speech=FakeSpeech(stream),
        send=send,
        max_capture_seconds=max_seconds,
        max_frame_bytes=640,
        language="ru",
    )
    return registry, pipeline, stream, sent


async def start_capture(registry: VoiceTurnRegistry):
    capture_id = uuid4()
    await registry.start(SpeechStart(capture_id=capture_id))
    return capture_id


async def test_speech_end_is_idempotent() -> None:
    registry, _pipeline, stream, _sent = make_registry()
    capture_id = await start_capture(registry)

    await registry.end(str(capture_id))
    await registry.end(str(capture_id))

    assert stream.finalize_count == 1
    await registry.aclose()


async def test_watchdog_finalizes_capture_without_speech_end() -> None:
    registry, _pipeline, stream, _sent = make_registry(max_seconds=0.01)
    await start_capture(registry)

    await asyncio.sleep(0.03)

    assert stream.finalize_count == 1
    await registry.aclose()


async def test_invalid_binary_frame_aborts_capture() -> None:
    registry, _pipeline, stream, sent = make_registry()
    await start_capture(registry)

    await registry.push(b"\x00")

    assert stream.closed is True
    assert sent[-1].type == "error"
    assert sent[-1].code == "invalid_audio_frame"


async def test_late_provider_epoch_is_dropped_and_final_commits_once() -> None:
    registry, pipeline, stream, sent = make_registry()
    capture_id = await start_capture(registry)
    await registry.end(str(capture_id))

    await stream.queue.put(
        SttTranscriptEvent(
            capture_id=capture_id,
            provider_epoch=1,
            provider="late",
            text="устаревший текст",
        )
    )
    await stream.queue.put(
        SttFinalEvent(
            capture_id=capture_id,
            provider_epoch=0,
            provider="mock",
            text="актуальный текст",
            confidence=0.9,
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    transcripts = [event for event in sent if event.type == "transcript"]
    assert [event.text for event in transcripts] == ["актуальный текст"]
    assert len(pipeline.finals) == 1
