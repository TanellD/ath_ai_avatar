"""Потоковый разбор служебного emotion-префикса ответа персонажа."""

import re
from dataclasses import dataclass

from ath_contracts import Emotion

_MAX_PREFIX_CHARS = 80
_CLOSING_TAG_RE = re.compile(r"</emotion\s*>", re.IGNORECASE)

#: Служебный маркер с ЛЮБЫМ именем: `<emotion=...>`, `<intent=...>`, `<mood=...>`.
#:
#: Промпт просит ровно `<emotion=...>`, но слабая модель придумывает своё имя:
#: на живой сессии локальный Qwen выдал `<intent=neutral>`. Под литерал
#: `<emotion=` это не подошло, маркер не признали служебным — и он ушёл в
#: реплику, то есть в субтитры и в озвучку, вслух.
#:
#: Правило поэтому шире промпта: что бы модель ни поставила в начале в угловых
#: скобках, произнесено это быть не должно. Ужесточать промпт бесполезно —
#: завтра она напишет `<tone=...>`.
_ANY_MARKER_RE = re.compile(r"^<\s*[A-Za-z_][\w-]*\s*=\s*([^<>]*)>")

#: Тот же маркер, ещё не дописанный: «<int», «<intent=neut». Ждём продолжения,
#: а не отдаём в текст. Первый символ после «<» обязан быть буквой — иначе это
#: обычная реплика, начавшаяся со скобки, и задерживать её нельзя.
_PARTIAL_MARKER_RE = re.compile(r"^<\s*[A-Za-z_][\w-]*\s*=?[^<>]*$")


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
        has_possible_prefix = (
            stripped == "<"
            or bool(_ANY_MARKER_RE.match(stripped))
            or bool(_PARTIAL_MARKER_RE.match(stripped))
        )
        if stripped and not has_possible_prefix:
            return self._fallback_result(self._buffer)

        marker = _ANY_MARKER_RE.match(stripped)
        if marker:
            raw_emotion = marker.group(1).strip().lower()
            try:
                emotion = Emotion(raw_emotion)
            except ValueError:
                emotion = self._fallback
            remainder = stripped[marker.end() :].lstrip("\r\n ")
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
        looks_like_control = bool(_ANY_MARKER_RE.match(stripped)) or bool(
            _PARTIAL_MARKER_RE.match(stripped)
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
