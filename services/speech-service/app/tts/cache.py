"""Кэш синтезированного аудио поверх любого провайдера TTS.

Смысл — детерминированные фразы (docs/agent-initiative.md): самопредставление
персонажа собирается из имени и роли, заданных сценарием, поэтому текст
побайтово одинаков во всех сессиях с этой персоной. Синтезировать его заново
на каждый запуск незачем: это чистая задержка в самом заметном месте — первая
фраза, которую слышит сотрудник (§9, метрика 1).

Реализовано декоратором, а не правкой каждого провайдера: кэш ничего не знает
про Soniox или ElevenLabs, а они — про кэш. Заворачивается в factory.py.

Почему кэшируется весь текст, а не только «помеченный как шаблонный»: провайдер
не может знать, откуда пришла строка, а различать это через контракт означало
бы тащить флаг `cacheable` через gateway в TtsRequest ради оптимизации, которая
и так самонастраивается. Динамические реплики почти всегда уникальны, поэтому
просто не дают попаданий; от их накопления защищает граница словаря (LRU).
"""

import hashlib
from collections import OrderedDict
from collections.abc import AsyncIterator

from ath_contracts import Emotion, EmotionIntensity

from app.core.logging import get_logger
from app.tts.base import AudioChunk, TtsProvider

log = get_logger(__name__)


class CachingTtsProvider(TtsProvider):
    """Оборачивает провайдера и переиспользует аудио для повторяющегося текста."""

    def __init__(
        self,
        inner: TtsProvider,
        max_entries: int = 256,
        max_text_chars: int = 200,
    ) -> None:
        self._inner = inner
        self._max_entries = max_entries
        self._max_text_chars = max_text_chars
        self._entries: OrderedDict[tuple, list[AudioChunk]] = OrderedDict()

    @property
    def name(self) -> str:
        return f"cached:{self._inner.name}"

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        emotion: Emotion = Emotion.NEUTRAL,
        intensity: EmotionIntensity = EmotionIntensity.NORMAL,
        enhanced_prosody: bool = True,
    ) -> AsyncIterator[AudioChunk]:
        key = self._key(text, voice_id, emotion, intensity, enhanced_prosody)

        if key is not None and (cached := self._entries.get(key)) is not None:
            self._entries.move_to_end(key)
            log.debug("tts.cache_hit", provider=self._inner.name, chars=len(text))
            for chunk in cached:
                yield chunk
            return

        collected: list[AudioChunk] = []
        async for chunk in self._inner.synthesize(
            text, voice_id, emotion, intensity, enhanced_prosody
        ):
            collected.append(chunk)
            yield chunk

        # Кладём только после полного успешного прохода: оборванный на середине
        # синтез (перебивание, §6) даст обрезанное аудио, и закэшировать его
        # значило бы отдавать огрызок всем следующим сессиям.
        if key is not None and collected:
            self._entries[key] = collected
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    async def synthesize_stream(
        self,
        texts: AsyncIterator[str],
        voice_id: str | None = None,
        emotion: Emotion = Emotion.NEUTRAL,
        intensity: EmotionIntensity = EmotionIntensity.NORMAL,
        enhanced_prosody: bool = True,
    ) -> AsyncIterator[AudioChunk]:
        """Не разбивать живую реплику на отдельные синтезы ради кэша.

        Инкрементальный текст уникален и не даёт полезных попаданий, а Soniox
        должен получить его в одном соединении, иначе между предложениями
        меняются громкость и просодия.
        """
        async for chunk in self._inner.synthesize_stream(
            texts, voice_id, emotion, intensity, enhanced_prosody
        ):
            yield chunk

    async def aclose(self) -> None:
        self._entries.clear()
        await self._inner.aclose()

    def _key(
        self,
        text: str,
        voice_id: str | None,
        emotion: Emotion,
        intensity: EmotionIntensity,
        enhanced_prosody: bool,
    ) -> tuple[str, str, str, str, bool] | None:
        """Ключ кэша либо None, если фразу кэшировать не стоит.

        Длинные куски отсекаются: это заведомо сгенерированный моделью текст,
        он уникален, попаданий не даст, а место в словаре займёт.

        В ключ входит и эмоция с интенсивностью: одна и та же фраза звучит
        по-разному в зависимости от них, и без этого раздражённое «Здравствуйте»
        подменялось бы нейтральным из кэша.
        """
        if len(text) > self._max_text_chars:
            return None
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return (voice_id or "", digest, emotion.value, intensity.value, enhanced_prosody)
