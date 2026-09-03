"""_wav_duration_ms — реальная длительность из WAV-заголовка, не оценка по
длине текста. От неё зависят тайминги SubtitleEvent (§7), а от них — синхронизация
текста с голосом на клиенте (панель истории диалога).
"""

import base64
import io
import wave

from app.orchestrator.pipeline import _wav_duration_ms


def _make_wav(duration_sec: float, sample_rate: int = 24000) -> str:
    frames = max(1, round(duration_sec * sample_rate))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frames)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_duration_matches_known_wav() -> None:
    data = _make_wav(1.5, sample_rate=24000)
    assert _wav_duration_ms(data) == 1500


def test_duration_rounds_to_nearest_ms() -> None:
    # 100 сэмплов при 24000 Гц = 4.1666... мс -> округляется до 4.
    data = _make_wav(100 / 24000, sample_rate=24000)
    assert _wav_duration_ms(data) == 4


def test_different_sample_rate() -> None:
    data = _make_wav(2.0, sample_rate=16000)
    assert _wav_duration_ms(data) == 2000
