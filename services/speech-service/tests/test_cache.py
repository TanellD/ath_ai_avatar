"""Кэш TTS: повтор детерминированной фразы не доходит до провайдера.

Смысл проверки — не «работает словарь», а то, ради чего кэш заведён: первая
фраза персонажа (самопредставление, docs/agent-initiative.md) одинакова во
всех сессиях, и второй её синтез обязан быть бесплатным.
"""

from collections.abc import AsyncIterator

from ath_contracts import Emotion, EmotionIntensity

from app.tts.base import AudioChunk, TtsProvider
from app.tts.cache import CachingTtsProvider


class CountingProvider(TtsProvider):
    """Считает вызовы и отдаёт по два чанка, чтобы проверить и порядок."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.closed = False

    @property
    def name(self) -> str:
        return "counting"

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        emotion: Emotion = Emotion.NEUTRAL,
        intensity: EmotionIntensity = EmotionIntensity.NORMAL,
        enhanced_prosody: bool = True,
    ) -> AsyncIterator[AudioChunk]:
        self.calls.append((text, voice_id))
        yield AudioChunk(data=b"first", sample_rate=24000)
        yield AudioChunk(data=b"second", sample_rate=24000, is_final=True)

    async def aclose(self) -> None:
        self.closed = True


async def _collect(
    provider: TtsProvider,
    text: str,
    voice_id: str | None = None,
    emotion: Emotion = Emotion.NEUTRAL,
) -> list[bytes]:
    return [chunk.data async for chunk in provider.synthesize(text, voice_id, emotion)]


async def test_second_call_is_served_from_cache() -> None:
    inner = CountingProvider()
    provider = CachingTtsProvider(inner)

    first = await _collect(provider, "Здравствуйте, меня зовут Ирина.")
    second = await _collect(provider, "Здравствуйте, меня зовут Ирина.")

    assert first == second == [b"first", b"second"]
    assert len(inner.calls) == 1, "повторный синтез той же фразы обязан быть из кэша"


async def test_emotion_is_part_of_the_key() -> None:
    """Одна фраза с разной эмоцией звучит по-разному.

    Регрессия слияния: кэш пришёл из ветки с ключом «голос + текст», а эмоции
    появились в main уже после. Без эмоции в ключе раздражённое «Здравствуйте»
    подменялось бы нейтральным, закэшированным раньше.
    """
    inner = CountingProvider()
    provider = CachingTtsProvider(inner)

    await _collect(provider, "Здравствуйте.", None, Emotion.NEUTRAL)
    await _collect(provider, "Здравствуйте.", None, Emotion.IRRITATED)

    assert len(inner.calls) == 2


async def test_voice_id_is_part_of_the_key() -> None:
    """Один и тот же текст разными голосами — разное аудио, не одно."""
    inner = CountingProvider()
    provider = CachingTtsProvider(inner)

    await _collect(provider, "Добрый день.", "nina")
    await _collect(provider, "Добрый день.", "boris")

    assert len(inner.calls) == 2


async def test_long_text_is_not_cached() -> None:
    """Длинная реплика заведомо сгенерирована моделью: попаданий не даст, а
    место займёт."""
    inner = CountingProvider()
    provider = CachingTtsProvider(inner, max_text_chars=20)

    long_text = "а" * 21
    await _collect(provider, long_text)
    await _collect(provider, long_text)

    assert len(inner.calls) == 2


async def test_cache_is_bounded() -> None:
    inner = CountingProvider()
    provider = CachingTtsProvider(inner, max_entries=2)

    for i in range(3):
        await _collect(provider, f"фраза {i}")

    # Самая старая вытеснена — её синтез повторится.
    await _collect(provider, "фраза 0")
    assert len(inner.calls) == 4


async def test_aclose_closes_inner_provider() -> None:
    inner = CountingProvider()
    provider = CachingTtsProvider(inner)

    await provider.aclose()

    assert inner.closed is True
