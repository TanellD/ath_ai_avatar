"""Регрессии конкретных ошибок Reese; тесты текста не оценивают звучание."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from ath_contracts import Emotion, EmotionIntensity
from soniox.realtime import RealtimeTTSConfig

from app.tts.russian_pronunciation import with_russian_stress
from app.tts.soniox import SonioxTtsProvider


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Какой эпитет! Охуенно.", "Какой эпи́тет! Охуе́нно."),
        ("ЭПИТЕТ, Эпитета, эпитетами.", "ЭПИ́ТЕТ, Эпи́тета, эпи́тетами."),
        ("ОХУЕННО? охуенно!", "ОХУЕ́ННО? охуе́нно!"),
        ("эпи́тет, охуе́нно", "эпи́тет, охуе́нно"),
        ("эпите́т, оху́енно", "эпите́т, оху́енно"),
        ("эпитетный test_эпитет эпитет2 myэпитет", "эпитетный test_эпитет эпитет2 myэпитет"),
        ("замок, мука, все и всё", "замок, мука, все и всё"),
        ("[warm] «эпитет»\nохуенно", "[warm] «эпи́тет»\nохуе́нно"),
        ("", ""),
    ],
)
def test_stress_hints(text: str, expected: str) -> None:
    result = with_russian_stress(text)
    assert result == expected
    assert with_russian_stress(result) == result


@pytest.mark.parametrize("language", ["ru", "en"])
async def test_provider_sends_hints_only_to_russian_tts(language: str) -> None:
    sent = []

    class Connection:
        async def send_text_chunks(self, text: str, *, text_end: bool) -> None:
            sent.append((text, text_end))

        async def receive_audio_chunks(self):
            yield b"\x00\x00" * 24

    @asynccontextmanager
    async def connect(*, config: RealtimeTTSConfig):
        assert config.language == language
        assert config.voice == "Reese"
        yield Connection()

    # Supply a fake transport without constructing the SDK or touching the network.
    provider = object.__new__(SonioxTtsProvider)
    provider._client = SimpleNamespace(
        realtime=SimpleNamespace(tts=SimpleNamespace(connect=connect)),
    )
    provider._default_voice = "Reese"
    provider._language = language
    provider._sample_rate = 24000
    original = "Нет, эпитет звучит охуенно."
    chunks = [chunk async for chunk in provider.synthesize(
        original, emotion=Emotion.NEUTRAL, intensity=EmotionIntensity.NORMAL,
    )]
    expected = "Нет, [pause] эпи́тет звучит охуе́нно." if language == "ru" else (
        "Нет, [pause] эпитет звучит охуенно."
    )
    assert sent == [(f"[calm] {expected}", True)]
    assert original == "Нет, эпитет звучит охуенно."
    assert len(chunks) == 1
    assert chunks[0].is_final
    assert chunks[0].data.startswith(b"RIFF")
