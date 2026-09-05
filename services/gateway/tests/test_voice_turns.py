import asyncio
from uuid import uuid4

from ath_contracts import SpeechStart
from ath_contracts.api import (
    SttFaultEvent,
    SttFinalEvent,
    SttProviderSwitchedEvent,
    SttTranscriptEvent,
)

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


class FakeRecovery:
    """Считает, сколько раз персонаж переспросил вслух."""

    def __init__(self, *, succeeds: bool = True) -> None:
        self._succeeds = succeeds
        self.plays: list[int] = []

    async def play(self, gen_id: int) -> bool:
        self.plays.append(gen_id)
        return self._succeeds


def make_registry(*, max_seconds: float = 20, recovery=None) -> tuple:  # noqa: ANN001
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
        recovery=recovery,
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


async def test_next_failover_epoch_is_accepted_and_old_epoch_is_dropped() -> None:
    registry, pipeline, stream, sent = make_registry()
    capture_id = await start_capture(registry)
    await registry.end(str(capture_id))

    await stream.queue.put(
        SttTranscriptEvent(
            capture_id=capture_id,
            provider_epoch=1,
            provider="gigaam",
            text="fallback partial",
        )
    )
    await stream.queue.put(
        SttFinalEvent(
            capture_id=capture_id,
            provider_epoch=0,
            provider="soniox",
            text="late primary final",
            confidence=0.9,
        )
    )
    await stream.queue.put(
        SttFinalEvent(
            capture_id=capture_id,
            provider_epoch=1,
            provider="gigaam",
            text="fallback final",
            confidence=None,
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    transcripts = [event for event in sent if event.type == "transcript"]
    assert [event.text for event in transcripts] == ["fallback partial", "fallback final"]
    assert len(pipeline.finals) == 1
    assert pipeline.finals[0]["text"] == "fallback final"


async def test_provider_switch_is_announced_to_the_browser() -> None:
    registry, _pipeline, stream, sent = make_registry()
    capture_id = await start_capture(registry)

    await stream.queue.put(
        SttTranscriptEvent(
            capture_id=capture_id,
            provider_epoch=0,
            provider="soniox",
            text="частичный текст",
        )
    )
    await stream.queue.put(
        SttProviderSwitchedEvent(
            capture_id=capture_id,
            provider_epoch=1,
            provider="gigaam",
            partials_available=False,
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    switches = [event for event in sent if event.type == "voice_provider_switched"]
    assert len(switches) == 1
    # Клиенту нужно именно исчезновение партиалов: без этого замерший черновик
    # выглядит как «микрофон перестал слышать», и человек начинает повторять.
    assert switches[0].partials_available is False
    assert switches[0].provider_epoch == 1
    assert switches[0].gen_id == 1


async def test_switch_from_an_unexpected_epoch_is_ignored() -> None:
    registry, _pipeline, stream, sent = make_registry()
    capture_id = await start_capture(registry)

    await stream.queue.put(
        SttProviderSwitchedEvent(
            capture_id=capture_id,
            provider_epoch=7,
            provider="gigaam",
            partials_available=False,
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert [event for event in sent if event.type == "voice_provider_switched"] == []


async def test_lost_turn_is_spoken_by_the_persona_instead_of_a_banner() -> None:
    recovery = FakeRecovery()
    registry, _pipeline, stream, sent = make_registry(recovery=recovery)
    capture_id = await start_capture(registry)

    await stream.queue.put(
        SttFaultEvent(
            capture_id=capture_id,
            provider_epoch=1,
            provider="gigaam",
            kind="internal",
            retryable=False,
            message="оба движка отказали",
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    errors = [event for event in sent if event.type == "error"]
    assert recovery.plays == [1]
    # ErrorEvent всё равно нужен: клиент по нему сбрасывает захват. Но spoken
    # говорит ему не рисовать баннер поверх уже сказанного вслух.
    assert len(errors) == 1
    assert errors[0].spoken is True


async def test_banner_returns_when_the_persona_cannot_speak() -> None:
    registry, _pipeline, stream, sent = make_registry(recovery=FakeRecovery(succeeds=False))
    capture_id = await start_capture(registry)

    await stream.queue.put(
        SttFaultEvent(
            capture_id=capture_id,
            provider_epoch=1,
            provider="gigaam",
            kind="internal",
            retryable=False,
            message="и TTS тоже лежит",
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    errors = [event for event in sent if event.type == "error"]
    assert errors[0].spoken is False


async def test_empty_final_is_treated_as_a_lost_turn() -> None:
    recovery = FakeRecovery()
    registry, pipeline, stream, sent = make_registry(recovery=recovery)
    capture_id = await start_capture(registry)
    await registry.end(str(capture_id))

    await stream.queue.put(
        SttFinalEvent(
            capture_id=capture_id,
            provider_epoch=0,
            provider="soniox",
            text="   ",
            confidence=None,
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # Человек говорил, распознавание отработало, текста нет — для него это
    # ровно та же потеря хода, что и отказ движка.
    assert recovery.plays == [1]
    assert pipeline.finals[0]["text"] == "   "
    assert [event.code for event in sent if event.type == "error"] == ["stt_empty_final"]
