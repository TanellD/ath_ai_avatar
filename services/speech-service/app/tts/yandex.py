"""Yandex SpeechKit TTS — не реализовано.

Кандидат номер один для русского голоса: нативный русский и низкая латентность
в РФ-регионе. Что нужно при подключении:

  - gRPC-стриминг SpeechKit v3 (`tts.api.cloud.yandex.net:443`), не REST v1:
    REST отдаёт результат целиком;
  - авторизация — `Api-Key` из `YANDEX_API_KEY` плюс `x-folder-id`;
  - формат `RAW_LINEAR16_PCM`, sample rate согласовать с TTS_SAMPLE_RATE;
  - проверить произношение цен и числительных («три тысячи двести рублей») —
    ровно то, на чём в отчёте держатся цитаты (§7).

Референсный проект дёргает SpeechKit из Python-сервиса `emotions-parser`
(`sentiment_analyzer.py`) — там же лежит рабочий пример авторизации.
"""

from collections.abc import AsyncIterator

from ath_contracts import Emotion, EmotionIntensity

from app.tts.base import AudioChunk, TtsProvider


class YandexTtsProvider(TtsProvider):
    def __init__(
        self, api_key: str, folder_id: str, default_voice_id: str, sample_rate: int
    ) -> None:
        self._api_key = api_key
        self._folder_id = folder_id
        self._default_voice_id = default_voice_id
        self._sample_rate = sample_rate

    @property
    def name(self) -> str:
        return "yandex"

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        emotion: Emotion = Emotion.NEUTRAL,
        intensity: EmotionIntensity = EmotionIntensity.NORMAL,
    ) -> AsyncIterator[AudioChunk]:
        raise NotImplementedError(
            "Yandex SpeechKit TTS не подключён. Используйте TTS_PROVIDER=mock либо "
            "реализуйте gRPC-стриминг — см. докстринг модуля."
        )
        yield  # pragma: no cover
