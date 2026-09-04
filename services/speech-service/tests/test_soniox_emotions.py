"""Soniox-теги остаются внутренней деталью TTS и не меняют текст сессии."""

import pytest
from ath_contracts import Emotion, EmotionIntensity

from app.tts.soniox import text_with_emotion, with_enhanced_prosody


@pytest.mark.parametrize(
    ("emotion", "expected"),
    [
        (Emotion.NEUTRAL, "[calm] Проверка"),
        (Emotion.FRIENDLY, "[warm] [reassuringly] Проверка"),
        (Emotion.IRRITATED, "[annoyed] [getting louder] Проверка"),
        (Emotion.ANGRY, "[angry] [loudly] Проверка"),
        (Emotion.SAD, "[sad] [softly] Проверка"),
        (Emotion.EXCITED, "[excited] [quickly] Проверка"),
        (Emotion.SURPRISED, "[surprised] [high-pitched] Проверка"),
    ],
)
def test_text_with_emotion(emotion: Emotion, expected: str) -> None:
    assert text_with_emotion("Проверка", emotion) == expected


@pytest.mark.parametrize(
    ("emotion", "intensity", "expected"),
    [
        (Emotion.IRRITATED, EmotionIntensity.SOFT, "[annoyed] [muttering] Проверка"),
        (Emotion.IRRITATED, EmotionIntensity.STRONG, "[annoyed] [loudly] Проверка"),
        (Emotion.ANGRY, EmotionIntensity.STRONG, "[angry] [shouting] Проверка"),
        (Emotion.SAD, EmotionIntensity.STRONG, "[sad] [trembling voice] Проверка"),
        (Emotion.EXCITED, EmotionIntensity.STRONG, "[excited] [loudly] Проверка"),
        (Emotion.SURPRISED, EmotionIntensity.STRONG, "[gasps] [surprised] Проверка"),
    ],
)
def test_text_with_emotion_intensity(
    emotion: Emotion, intensity: EmotionIntensity, expected: str
) -> None:
    assert text_with_emotion("Проверка", emotion, intensity) == expected


def test_with_enhanced_prosody_adds_only_semantic_pauses() -> None:
    text = "Нет, это возможно, но потребует времени, сил и внимания."
    assert with_enhanced_prosody(text) == (
        "Нет, [pause] это возможно, [pause] но потребует времени, сил и внимания."
    )


def test_text_with_emotion_can_disable_enhanced_prosody() -> None:
    assert text_with_emotion(
        "Нет, это невозможно.",
        Emotion.ANGRY,
        EmotionIntensity.STRONG,
        enhanced_prosody=False,
    ) == "[angry] [shouting] Нет, это невозможно."
