"""Реальный потоковый TTS через Soniox — Claude.md §10.

Провалидирован веткой `poc`: рабочий русский голос ("Nina") в реальном
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
import uuid
import wave
from collections.abc import AsyncIterator

from soniox import AsyncSonioxClient
from soniox.realtime import RealtimeTTSConfig

from app.core.logging import get_logger
from app.tts.base import AudioChunk, TtsProvider

log = get_logger(__name__)

_MODEL = "tts-rt-v2"


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
        self, text: str, voice_id: str | None = None
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
            await connection.send_text_chunks(text, text_end=True)

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
