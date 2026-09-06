"""Soniox-теги остаются внутренней деталью TTS и не меняют текст сессии."""

import pytest
from ath_contracts import Emotion, EmotionIntensity

from app.tts.soniox import (
    TimestampControlTagFilter,
    spoken_text_chunks,
    text_with_emotion,
    with_enhanced_prosody,
)


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


@pytest.mark.asyncio
async def test_stream_uses_one_emotion_prefix_for_the_whole_reply() -> None:
    async def sentences():
        yield "Нет, это возможно."
        yield "Но потребуется время."

    result = [
        chunk
        async for chunk in spoken_text_chunks(
            sentences(), Emotion.FRIENDLY, EmotionIntensity.STRONG, True
        )
    ]

    assert result == [
        "[delighted] [warm] Нет, [pause] это возможно.",
        " Но потребуется время.",
    ]
    assert "[delighted]" not in result[1]


def test_timestamp_filter_hides_control_tags_split_between_events() -> None:
    value = TimestampControlTagFilter()

    first = value.apply(list("[deligh"), [0.0] * 7, [0.1] * 7)
    second = value.apply(list("ted] Привет, [pau"), [0.2] * 17, [0.3] * 17)
    third = value.apply(list("se] мир"), [0.4] * 7, [0.5] * 7)

    assert first[0] == ""
    assert second[0] == " Привет, "
    assert third[0] == " мир"
    assert len(second[0]) == len(second[1]) == len(second[2])
