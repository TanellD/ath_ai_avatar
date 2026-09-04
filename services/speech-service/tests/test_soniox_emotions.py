"""Soniox-теги остаются внутренней деталью TTS и не меняют текст сессии."""

import pytest
from ath_contracts import Mood

from app.tts.soniox import text_with_mood


@pytest.mark.parametrize(
    ("mood", "expected"),
    [
        (Mood.NEUTRAL, "[calm] Проверка"),
        (Mood.FRIENDLY, "[warm] Проверка"),
        (Mood.IRRITATED, "[annoyed] Проверка"),
    ],
)
def test_text_with_mood(mood: Mood, expected: str) -> None:
    assert text_with_mood("Проверка", mood) == expected
