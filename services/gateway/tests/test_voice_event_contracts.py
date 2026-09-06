"""Контракт voice control отделён от бинарных audio frames."""

from uuid import uuid4

import pytest
from ath_contracts import SilenceTimeout, SpeechAbort, SpeechEnd, SpeechStart, parse_client_event
from pydantic import ValidationError


def test_speech_start_accepts_canonical_pcm_only() -> None:
    capture_id = uuid4()

    event = parse_client_event(
        {
            "type": "speech_start",
            "capture_id": str(capture_id),
            "interrupts": 4,
            "mode": "ptt",
            "audio_format": "pcm_s16le",
            "sample_rate": 16000,
            "num_channels": 1,
        }
    )

    assert isinstance(event, SpeechStart)
    assert event.capture_id == capture_id
    assert event.sample_rate == 16000


@pytest.mark.parametrize(
    ("field", "value"),
    [("audio_format", "webm"), ("sample_rate", 48000), ("num_channels", 2)],
)
def test_speech_start_rejects_noncanonical_audio(field: str, value: object) -> None:
    payload: dict[str, object] = {
        "type": "speech_start",
        "capture_id": str(uuid4()),
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        parse_client_event(payload)


def test_speech_end_is_correlated_by_capture_id() -> None:
    capture_id = uuid4()
    event = parse_client_event({"type": "speech_end", "capture_id": str(capture_id)})

    assert isinstance(event, SpeechEnd)
    assert event.capture_id == capture_id


def test_speech_abort_is_correlated_by_capture_id() -> None:
    capture_id = uuid4()
    event = parse_client_event({"type": "speech_abort", "capture_id": str(capture_id)})

    assert isinstance(event, SpeechAbort)
    assert event.capture_id == capture_id


@pytest.mark.parametrize("phase", ["nudge", "continue"])
def test_silence_timeout_accepts_two_phases(phase: str) -> None:
    event = parse_client_event({"type": "silence_timeout", "phase": phase})

    assert isinstance(event, SilenceTimeout)
    assert event.phase == phase


def test_silence_timeout_rejects_unknown_phase() -> None:
    with pytest.raises(ValidationError):
        parse_client_event({"type": "silence_timeout", "phase": "finish"})
