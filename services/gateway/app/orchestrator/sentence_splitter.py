"""Разбиение потока токенов на предложения для TTS — Claude.md §10.

Первое предложение уходит в TTS сразу, не дожидаясь конца генерации LLM. Это
то, что удерживает метрику 1 (time to first audio p95 ≤ 3 с): пользователь
слышит начало ответа, пока модель ещё пишет его конец.

Реализовано целиком — модуль на тридцать строк, а заглушка здесь ломает
основную латентностную гипотезу.
"""

import re
from collections.abc import Iterator

# Границы предложения в русском тексте. Многоточие и «!?» — один разрыв, не три.
_BOUNDARY = re.compile(r"(?<=[.!?…])[\"»)]?\s+")

# Не резать на инициалах и распространённых сокращениях: «И. И. Иванов»,
# «т. е.», «руб.» — иначе TTS получит огрызок и произнесёт его с падающей
# интонацией.
_ABBREVIATIONS = ("т.е.", "т.к.", "т.д.", "т.п.", "руб.", "тыс.", "млн.", "г.", "стр.")

_MIN_CHUNK_CHARS = 12
"""Слишком короткий кусок («Да.») лучше склеить со следующим: отдельный
TTS-вызов на два слова стоит дороже, чем звучит."""


class SentenceSplitter:
    """Инкрементальный сплиттер: кормим токенами, забираем готовые предложения."""

    def __init__(self, min_chunk_chars: int = _MIN_CHUNK_CHARS) -> None:
        self._buffer = ""
        self._min_chunk_chars = min_chunk_chars

    def feed(self, token: str) -> Iterator[str]:
        """Добавить токен. Выдаёт предложения, которые уже можно озвучивать."""
        self._buffer += token

        while True:
            match = _BOUNDARY.search(self._buffer)
            if match is None:
                return

            candidate = self._buffer[: match.start()].strip()

            if self._is_abbreviation_tail(candidate) or len(candidate) < self._min_chunk_chars:
                # Не граница — ждём продолжения, буфер не трогаем.
                return

            self._buffer = self._buffer[match.end() :]
            yield candidate

    def flush(self) -> str | None:
        """Хвост после конца генерации. Вызывать ровно один раз, в конце потока."""
        tail = self._buffer.strip()
        self._buffer = ""
        return tail or None

    @staticmethod
    def _is_abbreviation_tail(text: str) -> bool:
        lowered = text.lower()
        if any(lowered.endswith(abbr) for abbr in _ABBREVIATIONS):
            return True
        # Инициал: одиночная заглавная буква с точкой в конце.
        return bool(re.search(r"\b[А-ЯA-Z]\.$", text))
