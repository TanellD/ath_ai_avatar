"""ElevenLabs streaming TTS — не реализовано.

Что нужно сделать при подключении:

  - WebSocket `wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input`,
    а не HTTP-эндпоинт: HTTP отдаёт файл целиком и проваливает требование §3
    («пользователь не ждёт генерации целиком»);
  - `output_format=pcm_24000` — сырой PCM без контейнера, чтобы клиенту не
    приходилось склеивать WAV-заголовки между чанками;
  - замерить время до первого чанка на русском тексте: бюджет 150-400 мс (§9).
    Если провайдер систематически выходит за 400 мс, это повод менять
    провайдера, а не растягивать бюджет.

Голос персонажа берётся из `scenario.persona.voice_id` (§7) и приходит
параметром `voice_id`; `TTS_VOICE_ID` из конфига — только дефолт.
"""

from collections.abc import AsyncIterator

from ath_contracts import Emotion, EmotionIntensity

from app.tts.base import AudioChunk, TtsProvider


class ElevenLabsTtsProvider(TtsProvider):
    def __init__(self, api_key: str, default_voice_id: str, sample_rate: int) -> None:
        self._api_key = api_key
        self._default_voice_id = default_voice_id
        self._sample_rate = sample_rate

    @property
    def name(self) -> str:
        return "elevenlabs"

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        emotion: Emotion = Emotion.NEUTRAL,
        intensity: EmotionIntensity = EmotionIntensity.NORMAL,
        enhanced_prosody: bool = True,
    ) -> AsyncIterator[AudioChunk]:
        raise NotImplementedError(
            "ElevenLabs TTS не подключён. Используйте TTS_PROVIDER=mock либо "
            "реализуйте потоковый вызов — см. докстринг модуля."
        )
        yield  # pragma: no cover — делает функцию генератором для типизации
