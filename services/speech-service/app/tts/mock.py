"""Заглушка TTS: тишина правдоподобной длительности, нарезанная как настоящий поток.

Провайдер по умолчанию. Смысл не в «чтобы собиралось», а в том, что на нём
проверяются три вещи, не требующие живого голоса:

  - часы воспроизведения и липсинк работают от currentTime реального аудио;
  - перебивание действительно обрывает поток на середине (метрика 4);
  - каденция чанков не ломает буферизацию клиента.

Длительность считается по числу символов при типовом темпе русской речи, чтобы
поведение походило на настоящее, а не отдавало всё мгновенно.
"""

import asyncio
import io
import math
import struct
import wave
from collections.abc import AsyncIterator

from ath_contracts import Mood

from app.core.logging import get_logger
from app.tts.base import AudioChunk, TtsProvider

log = get_logger(__name__)

_CHARS_PER_SECOND = 14.0
"""Примерный темп русской речи. Ошибка здесь не критична: важна пропорция."""

_CHUNK_MS = 200
"""Размер чанка. Совпадает по порядку с тем, что отдают реальные потоковые TTS."""

_FIRST_CHUNK_DELAY_SEC = 0.18
"""Имитация времени до первого чанка — нижняя граница бюджета 150-400 мс (§9).
Без неё клиент тестируется в нереально благоприятных условиях."""


def _silence_wav(duration_sec: float, sample_rate: int) -> bytes:
    """WAV-контейнер с тишиной. Контейнер настоящий — клиент декодирует его
    штатным путём, без специальной ветки «это же мок»."""
    frames = max(1, int(duration_sec * sample_rate))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(struct.pack(f"<{frames}h", *([0] * frames)))
    return buffer.getvalue()


class MockTtsProvider(TtsProvider):
    def __init__(self, sample_rate: int) -> None:
        self._sample_rate = sample_rate

    @property
    def name(self) -> str:
        return "mock"

    async def synthesize(
        self, text: str, voice_id: str | None = None, mood: Mood = Mood.NEUTRAL
    ) -> AsyncIterator[AudioChunk]:
        total_sec = max(0.3, len(text) / _CHARS_PER_SECOND)
        chunk_sec = _CHUNK_MS / 1000
        chunk_count = max(1, math.ceil(total_sec / chunk_sec))

        log.debug("tts.mock.synthesize", chars=len(text), seconds=round(total_sec, 2))

        await asyncio.sleep(_FIRST_CHUNK_DELAY_SEC)

        for index in range(chunk_count):
            is_last = index == chunk_count - 1
            # Последний чанк короче, если длительность не делится нацело.
            seconds = min(chunk_sec, total_sec - index * chunk_sec)

            yield AudioChunk(
                data=_silence_wav(seconds, self._sample_rate),
                sample_rate=self._sample_rate,
                is_final=is_last,
            )

            if not is_last:
                # Отдаём чуть быстрее реального времени: клиент должен успевать
                # набирать буфер, но не получать всё разом.
                await asyncio.sleep(chunk_sec * 0.5)
