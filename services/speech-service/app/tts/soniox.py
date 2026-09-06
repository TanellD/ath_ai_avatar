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

import asyncio
import io
import re
import uuid
import wave
from collections.abc import AsyncIterator
from contextlib import suppress

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


class TimestampControlTagFilter:
    """Убирает Soniox control tags из отображаемого timestamp-текста.

    Один тег может быть разрезан между соседними realtime-событиями, поэтому
    состояние хранится на протяжении всего TTS stream.
    """

    def __init__(self) -> None:
        self._inside_tag = False

    def apply(
        self, characters: list[str], starts: list[float], ends: list[float]
    ) -> tuple[str, list[float], list[float]]:
        visible: list[str] = []
        visible_starts: list[float] = []
        visible_ends: list[float] = []
        for character, start, end in zip(characters, starts, ends, strict=False):
            if self._inside_tag:
                if character == "]":
                    self._inside_tag = False
                continue
            if character == "[":
                self._inside_tag = True
                continue
            visible.append(character)
            visible_starts.append(start)
            visible_ends.append(end)
        return "".join(visible), visible_starts, visible_ends


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


async def spoken_text_chunks(
    texts: AsyncIterator[str],
    emotion: Emotion,
    intensity: EmotionIntensity,
    enhanced_prosody: bool,
) -> AsyncIterator[str]:
    """Подготовить LLM-части для одного Soniox stream.

    Emotion-теги задают подачу всей реплики и поэтому отправляются ровно один
    раз. Пробел между предложениями нужен, потому что SentenceSplitter отдаёт
    очищенные строки.
    """
    first = True
    async for text in texts:
        spoken = with_enhanced_prosody(text) if enhanced_prosody else text
        if not spoken.strip():
            continue
        if first:
            yield f"{_EMOTION_TAGS[emotion][intensity]} {spoken}"
            first = False
        else:
            yield f" {spoken}"


_IDLE_GUARD_SEC = 4.0
"""Сколько ждать следующий кусок текста, прежде чем закрыть сессию Soniox.

Замерено на живом сервисе: паузы по 4 с — 3 успеха из 4, паузы по 10 с — 0 из
4, каждый обрыв ровно на 10.0 с. Берём с запасом вдвое: 4 с ещё почти всегда
проходят сами, а лишнее переоткрытие стоит одного рукопожатия и случается
только тогда, когда LLM и так задумалась.
"""

_PULL_DONE = object()
"""Исходный поток текста кончился. Часовой, а не исключение: StopAsyncIteration
из задачи ловится неудобно и легко теряется."""


async def _pull_next(source: AsyncIterator[str]) -> object:
    try:
        return await anext(source)
    except StopAsyncIteration:
        return _PULL_DONE


async def _idle_bounded_batches(
    source: AsyncIterator[str], idle_sec: float
) -> AsyncIterator[list[str]]:
    """Резать поток текста на пачки, ни одна из которых не ждала дольше idle_sec.

    ПЕРВОГО куска пачки ждём без ограничения: пока его нет, ни одной сессии не
    открыто и таймаут Soniox не тикает — ждать можно сколько угодно. А вот
    внутри уже начатой пачки пауза означает открытое соединение, и её обрываем.

    Задача чтения переживает тайм-аут (`shield`) и дочитывается следующей
    итерацией — иначе кусок, пришедший в момент нарезки, потерялся бы.
    """
    puller: asyncio.Task[object] | None = None
    batch: list[str] = []
    try:
        while True:
            if puller is None:
                puller = asyncio.create_task(_pull_next(source))
            try:
                item = await asyncio.wait_for(
                    asyncio.shield(puller), timeout=idle_sec if batch else None
                )
            except TimeoutError:
                yield batch
                batch = []
                continue

            puller = None
            if item is _PULL_DONE:
                if batch:
                    yield batch
                return
            batch.append(item)  # type: ignore[arg-type]
    finally:
        if puller is not None:
            puller.cancel()
            with suppress(asyncio.CancelledError):
                await puller


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
        async def one_text() -> AsyncIterator[str]:
            yield text

        async for chunk in self.synthesize_stream(
            one_text(), voice_id, emotion, intensity, enhanced_prosody
        ):
            yield chunk

    async def synthesize_stream(
        self,
        texts: AsyncIterator[str],
        voice_id: str | None = None,
        emotion: Emotion = Emotion.NEUTRAL,
        intensity: EmotionIntensity = EmotionIntensity.NORMAL,
        enhanced_prosody: bool = True,
    ) -> AsyncIterator[AudioChunk]:
        """Озвучить реплику, не давая сессии Soniox простаивать.

        Soniox обрывает открытую сессию, если текста в неё долго не приходит, и
        присылает событие с `error_code=408`. Порог не документирован, но
        измерен на живом сервисе: паузы по 4 с между кусками — 3 успеха из 4,
        паузы по 10 с — 0 из 4, причём каждый обрыв ровно на 10.0 с. Без пауз
        подряд 4 успеха из 4.

        А `texts` — это `sentences()`, темп которого задаёт LLM. Пока модель
        думает над следующим предложением, сессия висит пустой: на медленном
        провайдере ход падал целиком, и вместо ответа персонажа звучала
        запасная скриптовая реплика.

        Поэтому поток режется на пачки: как только текст замолкает дольше
        порога, текущая сессия закрывается штатным `text_end`, а следующая
        открывается уже под новый текст. Аудио от этого не рвётся — куски
        просто идут дальше по очереди, — а ожидание LLM больше не тикает ни в
        одном открытом соединении.
        """
        spoken = spoken_text_chunks(texts, emotion, intensity, enhanced_prosody)
        # У новой сессии нет памяти о подаче: тег эмоции повторяем в начале
        # каждой следующей пачки, иначе хвост реплики зазвучит нейтрально.
        prefix = _EMOTION_TAGS[emotion][intensity]

        pending: AudioChunk | None = None
        produced = False
        first_batch = True

        async for batch in _idle_bounded_batches(spoken, _IDLE_GUARD_SEC):
            if not first_batch:
                batch = [f"{prefix} {batch[0].lstrip()}", *batch[1:]]
            first_batch = False

            async for chunk in self._synthesize_batch(batch, voice_id):
                produced = True
                # На один кусок позади: `is_final` ставится только последнему
                # за всю реплику, а не последнему в каждой пачке.
                if pending is not None:
                    yield pending
                pending = chunk

        if pending is not None:
            yield AudioChunk(
                data=pending.data,
                sample_rate=pending.sample_rate,
                is_final=True,
                subtitle_text=pending.subtitle_text,
                subtitle_start_ms=pending.subtitle_start_ms,
                subtitle_end_ms=pending.subtitle_end_ms,
            )
        elif not produced:
            log.warning("tts.soniox.empty_response")

    async def _synthesize_batch(
        self, batch: list[str], voice_id: str | None
    ) -> AsyncIterator[AudioChunk]:
        """Одна пачка текста — одна сессия Soniox. `is_final` здесь не ставится."""
        config = RealtimeTTSConfig(
            stream_id=str(uuid.uuid4()),
            model=_MODEL,
            language=self._language,
            voice=voice_id or self._default_voice,
            audio_format="pcm_s16le",
            sample_rate=self._sample_rate,
            return_timestamps=True,
        )

        async def batch_chunks() -> AsyncIterator[str]:
            for chunk in batch:
                yield chunk

        # Отмена (§6): при task.cancel() со стороны gateway CancelledError
        # прорастает сквозь `async for` ниже, и `async with` гарантированно
        # вызывает __aexit__ соединения на разворачивании стека — отдельно
        # закрывать сокет не нужно.
        async with self._client.realtime.tts.connect(config=config) as connection:
            sender = asyncio.create_task(
                connection.send_text_chunks(batch_chunks(), text_end=True)
            )
            events = connection.receive_events().__aiter__()
            timestamp_filter = TimestampControlTagFilter()
            try:
                while True:
                    receiver = asyncio.create_task(anext(events))
                    if sender is not None:
                        done, _ = await asyncio.wait(
                            {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
                        )
                        if sender in done:
                            try:
                                sender.result()
                            except BaseException:
                                receiver.cancel()
                                with suppress(asyncio.CancelledError):
                                    await receiver
                                raise
                            sender = None
                    try:
                        event = await receiver
                    except StopAsyncIteration:
                        break

                    pcm = event.audio_bytes()
                    if pcm is None:
                        continue
                    timestamps = event.timestamps
                    if timestamps is None:
                        aligned_text, starts, ends = "", [], []
                    else:
                        aligned_text, starts, ends = timestamp_filter.apply(
                            timestamps.characters,
                            timestamps.character_start_times_seconds,
                            timestamps.character_end_times_seconds,
                        )
                    yield AudioChunk(
                        data=_pcm_to_wav(pcm, self._sample_rate),
                        sample_rate=self._sample_rate,
                        subtitle_text=aligned_text,
                        subtitle_start_ms=round(starts[0] * 1000) if starts else None,
                        subtitle_end_ms=round(ends[-1] * 1000) if ends else None,
                    )
            finally:
                if sender is not None:
                    sender.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await sender
