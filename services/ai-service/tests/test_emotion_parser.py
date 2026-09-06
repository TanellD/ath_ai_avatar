"""Emotion-префикс разбирается до выдачи видимого текста."""

from ath_contracts import Emotion

from app.character.emotion_parser import EmotionPrefixParser


def test_prefix_can_arrive_in_separate_chunks() -> None:
    parser = EmotionPrefixParser(Emotion.NEUTRAL)

    assert parser.feed("<emo").text == ""
    assert parser.feed("tion=surprised>").emotion is Emotion.SURPRISED
    assert parser.feed("Правда?").text == "Правда?"


def test_text_after_prefix_is_emitted_without_marker() -> None:
    parser = EmotionPrefixParser(Emotion.NEUTRAL)

    result = parser.feed("<emotion=excited>\nОтличная новость!")

    assert result.emotion is Emotion.EXCITED
    assert result.text == "Отличная новость!"


def test_unknown_emotion_uses_fallback_and_hides_marker() -> None:
    parser = EmotionPrefixParser(Emotion.IRRITATED)

    result = parser.feed("<emotion=confused>\nПовторите, пожалуйста.")

    assert result.emotion is Emotion.IRRITATED
    assert result.text == "Повторите, пожалуйста."


def test_missing_prefix_does_not_hold_first_token() -> None:
    parser = EmotionPrefixParser(Emotion.FRIENDLY)

    result = parser.feed("Здравствуйте")

    assert result.emotion is Emotion.FRIENDLY
    assert result.text == "Здравствуйте"


def test_incomplete_prefix_falls_back_on_finish() -> None:
    parser = EmotionPrefixParser(Emotion.NEUTRAL)
    parser.feed("<emotion=exc")

    result = parser.finish()

    assert result.emotion is Emotion.NEUTRAL
    assert result.text == ""


def test_closing_tag_is_removed_from_visible_text() -> None:
    parser = EmotionPrefixParser(Emotion.NEUTRAL)

    result = parser.feed("<emotion=irritated>Нет, это дорого.</emotion>")

    assert result.emotion is Emotion.IRRITATED
    assert result.text == "Нет, это дорого."


def test_closing_tag_can_arrive_across_chunks() -> None:
    parser = EmotionPrefixParser(Emotion.NEUTRAL)
    assert parser.feed("<emotion=friendly>Хорошо.").text == "Хорошо."

    assert parser.feed("</emo").text == ""
    assert parser.feed("tion> Продолжим.").text == " Продолжим."
