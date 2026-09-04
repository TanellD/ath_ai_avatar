"""Потоковый разбор служебного emotion-префикса ответа персонажа."""

from dataclasses import dataclass

from ath_contracts import Emotion

_PREFIX_START = "<emotion="
_MAX_PREFIX_CHARS = 80


@dataclass(frozen=True)
class EmotionParseResult:
    emotion: Emotion | None = None
    text: str = ""


class EmotionPrefixParser:
    """Удаляет `<emotion=name>` из потока и всегда выбирает безопасный fallback."""

    def __init__(self, fallback: Emotion) -> None:
        self._fallback = fallback
        self._buffer = ""
        self._resolved = False

    def feed(self, chunk: str) -> EmotionParseResult:
        if self._resolved:
            return EmotionParseResult(text=chunk)

        self._buffer += chunk
        stripped = self._buffer.lstrip()

        # Как только видно, что заголовка нет, не задерживаем первый токен.
        has_possible_prefix = _PREFIX_START.startswith(stripped) or stripped.startswith(
            _PREFIX_START
        )
        if stripped and not has_possible_prefix:
            return self._fallback_result(self._buffer)

        closing = stripped.find(">")
        if closing >= 0:
            raw_emotion = stripped[len(_PREFIX_START) : closing].strip().lower()
            try:
                emotion = Emotion(raw_emotion)
            except ValueError:
                emotion = self._fallback
            remainder = stripped[closing + 1 :].lstrip("\r\n ")
            self._resolved = True
            self._buffer = ""
            return EmotionParseResult(emotion=emotion, text=remainder)

        if len(self._buffer) > _MAX_PREFIX_CHARS:
            return self._fallback_result(self._buffer)

        return EmotionParseResult()

    def finish(self) -> EmotionParseResult:
        if self._resolved:
            return EmotionParseResult()
        return self._fallback_result(self._buffer)

    def _fallback_result(self, text: str) -> EmotionParseResult:
        self._resolved = True
        self._buffer = ""
        stripped = text.lstrip()
        looks_like_control = stripped.startswith(_PREFIX_START) or _PREFIX_START.startswith(
            stripped
        )
        return EmotionParseResult(
            emotion=self._fallback,
            text="" if looks_like_control else text,
        )
