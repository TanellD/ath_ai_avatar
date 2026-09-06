"""Потоковый разбор служебного emotion-префикса ответа персонажа."""

import re
from dataclasses import dataclass

from ath_contracts import Emotion

_PREFIX_START = "<emotion="
_MAX_PREFIX_CHARS = 80
_CLOSING_TAG_RE = re.compile(r"</emotion\s*>", re.IGNORECASE)


@dataclass(frozen=True)
class EmotionParseResult:
    emotion: Emotion | None = None
    text: str = ""


class EmotionPrefixParser:
    """Удаляет `<emotion=name>` из потока и всегда выбирает безопасный fallback."""

    def __init__(self, fallback: Emotion) -> None:
        self._fallback = fallback
        self._buffer = ""
        self._text_buffer = ""
        self._resolved = False

    def feed(self, chunk: str) -> EmotionParseResult:
        if self._resolved:
            return EmotionParseResult(text=self._filter_closing_tag(chunk))

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
            return EmotionParseResult(
                emotion=emotion,
                text=self._filter_closing_tag(remainder),
            )

        if len(self._buffer) > _MAX_PREFIX_CHARS:
            return self._fallback_result(self._buffer)

        return EmotionParseResult()

    def finish(self) -> EmotionParseResult:
        if self._resolved:
            # Незавершённый `</emotion` в конце ответа тоже служебный мусор и
            # не должен становиться видимым текстом или уходить в TTS.
            self._text_buffer = ""
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
            text="" if looks_like_control else self._filter_closing_tag(text),
        )

    def _filter_closing_tag(self, chunk: str) -> str:
        """Удалить `</emotion>` даже на границе потоковых LLM-чанков."""
        combined = self._text_buffer + chunk
        self._text_buffer = ""
        visible = _CLOSING_TAG_RE.sub("", combined)

        # LLM-токен может закончиться на `</emo`, а следующий продолжить тег.
        # Удерживаем только такой хвост; обычный символ `<` выпускается сразу.
        marker = visible.rfind("<")
        if marker < 0:
            return visible

        tail = visible[marker:]
        lowered = tail.lower()
        whitespace_tail = lowered.startswith("</emotion") and (
            lowered[len("</emotion") :] == ""
            or lowered[len("</emotion") :].isspace()
        )
        if "</emotion>".startswith(lowered) or whitespace_tail:
            self._text_buffer = tail
            return visible[:marker]
        return visible
