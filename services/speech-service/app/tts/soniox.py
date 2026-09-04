"""Реальный потоковый TTS через Soniox — Claude.md §10.

Провалидирован веткой `poc`: рабочий русский голос ("Reese") в реальном
Node-сервере. Здесь — не порт того же кода, а собственная реализация поверх
проверенного контракта: API прочитан из официального Python-пакета `soniox`
(`pip install soniox`, `AsyncSonioxClient`), а не угадан по Node-сниппету.
Использован именно потоковый realtime-эндпоинт, а не REST-`/tts` из ветки
`poc` — тот отдаёт файл целиком и провалил бы требование §3 «пользователь не
ждёт генерации целиком».

Один WebSocket-сеанс на предложение: `pipeline._synthesize` уже вызывает
`synthesize()` по одному предложению за раз (§10 — первое отправляется сразу,
не дожидаясь конца генерации LLM). Внутри одного предложения синтез всё равно
настоящий потоковый: чанки приходят по мере генерации речи, а не после
готовности целиком.

Проверенная форма API (`python -c "import inspect; ..."` против
установленного пакета, не документация из сниппета):

    AsyncSonioxClient(api_key=...)
    client.realtime.tts.connect(config=RealtimeTTSConfig(...))  -> async CM
    await connection.send_text_chunks(text, text_end=True)
    async for chunk in connection.receive_audio_chunks(): ...   # сырые байты
"""

import io
import re
import uuid
import wave
from collections.abc import AsyncIterator

from ath_contracts import Emotion, EmotionIntensity
from soniox import AsyncSonioxClient
from soniox.realtime import RealtimeTTSConfig

from app.core.logging import get_logger
from app.tts.base import AudioChunk, TtsProvider

log = get_logger(__name__)

_MODEL = "tts-rt-v2"

_EMOTION_TAGS = {
    Emotion.NEUTRAL: {
        EmotionIntensity.SOFT: "[calm] [softly]",
        EmotionIntensity.NORMAL: "[calm]",
        EmotionIntensity.STRONG: "[serious]",
    },
    Emotion.FRIENDLY: {
        EmotionIntensity.SOFT: "[warm] [softly]",
        EmotionIntensity.NORMAL: "[warm] [reassuringly]",
        EmotionIntensity.STRONG: "[delighted] [warm]",
    },
    Emotion.IRRITATED: {
        EmotionIntensity.SOFT: "[annoyed] [muttering]",
        EmotionIntensity.NORMAL: "[annoyed] [getting louder]",
        EmotionIntensity.STRONG: "[annoyed] [loudly]",
    },
    Emotion.ANGRY: {
        EmotionIntensity.SOFT: "[angry] [low voice]",
        EmotionIntensity.NORMAL: "[angry] [loudly]",
        EmotionIntensity.STRONG: "[angry] [shouting]",
    },
    Emotion.SAD: {
        EmotionIntensity.SOFT: "[disappointed] [softly]",
        EmotionIntensity.NORMAL: "[sad] [softly]",
        EmotionIntensity.STRONG: "[sad] [trembling voice]",
    },
    Emotion.EXCITED: {
        EmotionIntensity.SOFT: "[happy] [warm]",
        EmotionIntensity.NORMAL: "[excited] [quickly]",
        EmotionIntensity.STRONG: "[excited] [loudly]",
    },
    Emotion.SURPRISED: {
        EmotionIntensity.SOFT: "[curious] [surprised]",
        EmotionIntensity.NORMAL: "[surprised] [high-pitched]",
        EmotionIntensity.STRONG: "[gasps] [surprised]",
    },
}

_INTRODUCTORY_PAUSE_RE = re.compile(
    r"(^|[.!?]\s*)(да|нет|хорошо|итак|конечно|пожалуй|послушайте|смотрите|жаль),\s*",
    re.IGNORECASE,
)
_TURN_PAUSE_RE = re.compile(
    r",\s+(но|однако|поэтому|зато|впрочем|и всё же)\b",
    re.IGNORECASE,
)


def with_enhanced_prosody(text: str) -> str:
    """Добавить паузы только в TTS-копию текста на смысловых границах."""
    with_intro_pauses = _INTRODUCTORY_PAUSE_RE.sub(r"\1\2, [pause] ", text)
    return _TURN_PAUSE_RE.sub(r", [pause] \1", with_intro_pauses)


def text_with_emotion(
    text: str,
    emotion: Emotion,
    intensity: EmotionIntensity = EmotionIntensity.NORMAL,
    enhanced_prosody: bool = True,
) -> str:
    """Добавить управляющий тег только в запрос Soniox, не в текст сессии."""
    spoken_text = with_enhanced_prosody(text) if enhanced_prosody else text
    return f"{_EMOTION_TAGS[emotion][intensity]} {spoken_text}"


def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Обернуть кусок сырого PCM16 mono в самостоятельный WAV-контейнер.

    `receive_audio_chunks()` не документирует, что каждый выданный кусок сам
    по себе валидный WAV-файл — фрагментация потока по WebSocket-кадрам не
    обязана совпадать с границами контейнера, и заголовок мог достаться
    только первому куску. Клиент декодирует каждый `event.data` независимо
    (`decodeAudioData` на чанк, см. AudioQueue.enqueue), поэтому заголовок
    нужен на каждом куске — запрашиваем поэтому сырой `pcm_s16le`, а не
    `wav`, и оборачиваем сами, тем же способом, что и mock.py.
    """
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)
    return buffer.getvalue()


class SonioxTtsProvider(TtsProvider):
    def __init__(
        self, api_key: str, default_voice: str, language: str, sample_rate: int
    ) -> None:
        self._client = AsyncSonioxClient(api_key=api_key)
        self._default_voice = default_voice
        self._language = language
        self._sample_rate = sample_rate

    @property
    def name(self) -> str:
        return "soniox"

    async def aclose(self) -> None:
        await self._client.aclose()

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        emotion: Emotion = Emotion.NEUTRAL,
        intensity: EmotionIntensity = EmotionIntensity.NORMAL,
        enhanced_prosody: bool = True,
    ) -> AsyncIterator[AudioChunk]:
        config = RealtimeTTSConfig(
            stream_id=str(uuid.uuid4()),
            model=_MODEL,
            language=self._language,
            voice=voice_id or self._default_voice,
            audio_format="pcm_s16le",
            sample_rate=self._sample_rate,
        )

        # Отмена (§6): при task.cancel() со стороны gateway CancelledError
        # прорастает сквозь `async for` ниже, и `async with` гарантированно
        # вызывает __aexit__ соединения на разворачивании стека — отдельно
        # закрывать сокет не нужно.
        async with self._client.realtime.tts.connect(config=config) as connection:
            await connection.send_text_chunks(
                text_with_emotion(text, emotion, intensity, enhanced_prosody), text_end=True
            )

            # Однокусковый lookahead: SDK не помечает последний чанк сам —
            # is_final узнаём только когда async-итератор исчерпан, то есть
            # на кусок позже. Без этого некому было бы поставить is_final=True.
            pending: bytes | None = None
            async for chunk in connection.receive_audio_chunks():
                if pending is not None:
                    yield AudioChunk(
                        data=_pcm_to_wav(pending, self._sample_rate),
                        sample_rate=self._sample_rate,
                        is_final=False,
                    )
                pending = chunk

            if pending is not None:
                yield AudioChunk(
                    data=_pcm_to_wav(pending, self._sample_rate),
                    sample_rate=self._sample_rate,
                    is_final=True,
                )
            else:
                log.warning("tts.soniox.empty_response", chars=len(text))
