"""Соединение с Soniox открывается только когда есть что послать.

Живой сбой: Soniox сама шлёт событие с error_code=408 ("Request timeout"),
если сессия открыта, а текста в неё долго не приходит — порог нигде не
документирован, но обрывы наблюдались уже на ~7-8 с ожидания (реальная
трассировка: soniox.errors.SonioxRealtimeError: Request timeout (code 408)
внутри synthesize_stream). `texts` в pipeline._speak() — это `sentences()`,
темп которого задаёт LLM, а LLM у нас за нестабильным прокси. Раньше
connect() вызывался ДО того, как у LLM было готово хоть одно предложение —
секундомер Soniox тикал всё это время впустую.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.tts.soniox import SonioxTtsProvider


class FakeEvent:
    def __init__(self, pcm: bytes | None) -> None:
        self._pcm = pcm
        self.timestamps = None

    def audio_bytes(self) -> bytes | None:
        return self._pcm


class FakeConnection:
    async def send_text_chunks(self, texts: AsyncIterator[str], text_end: bool = True) -> None:
        async for _ in texts:
            pass

    def receive_events(self):
        async def one_event() -> AsyncIterator[FakeEvent]:
            yield FakeEvent(b"\x00\x00")

        return one_event()


class FakeTtsNamespace:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    @asynccontextmanager
    async def connect(self, config):  # noqa: ANN001
        self._log.append("connect")
        yield FakeConnection()


class FakeRealtime:
    def __init__(self, log: list[str]) -> None:
        self.tts = FakeTtsNamespace(log)


class FakeSonioxClient:
    def __init__(self, log: list[str]) -> None:
        self.realtime = FakeRealtime(log)

    async def aclose(self) -> None:
        pass


def _provider(log: list[str]) -> SonioxTtsProvider:
    provider = SonioxTtsProvider(
        api_key="test", default_voice="Reese", language="ru", sample_rate=24000
    )
    provider._client = FakeSonioxClient(log)
    return provider


async def test_connect_waits_for_the_first_text_chunk() -> None:
    log: list[str] = []
    provider = _provider(log)

    async def slow_llm() -> AsyncIterator[str]:
        log.append("waiting_for_llm")
        # Событие цикла, а не время: следующая строка обязана выполниться
        # только после того, как тест увидит "connect() ещё не звали".
        yield "Здравствуйте, чем могу помочь?"

    async for _chunk in provider.synthesize_stream(slow_llm()):
        pass

    assert log == ["waiting_for_llm", "connect"], (
        "Soniox-сессия не должна открываться раньше, чем LLM дал первый кусок текста"
    )


async def test_empty_reply_never_opens_a_connection() -> None:
    """Пустой ответ LLM (splitter ничего не собрал) — синтезировать нечего,
    и открывать сессию с Soniox ради этого не нужно."""
    log: list[str] = []
    provider = _provider(log)

    async def empty() -> AsyncIterator[str]:
        return
        yield  # pragma: no cover — делает функцию асинхронным генератором

    chunks = [chunk async for chunk in provider.synthesize_stream(empty())]

    assert chunks == []
    assert log == []
