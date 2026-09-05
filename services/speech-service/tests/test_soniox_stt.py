import json
from uuid import uuid4

from app.stt.base import FinalizationComplete, RecognitionIdentity, SttSessionConfig
from app.stt.soniox import SonioxSttProvider


class FakeWebSocket:
    def __init__(self, messages: list[dict]) -> None:
        self._messages = iter(json.dumps(message) for message in messages)
        self.sent: list[str | bytes] = []
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        try:
            return next(self._messages)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def send(self, value: str | bytes) -> None:
        self.sent.append(value)

    async def close(self) -> None:
        self.closed = True


async def test_soniox_finalizes_only_on_fin_marker() -> None:
    identity = RecognitionIdentity("session", uuid4(), 0, "soniox")
    provider = SonioxSttProvider(api_key="test", model="stt-rt-v5", websocket_url="wss://test")
    provider._config = SttSessionConfig(identity, "ru", "pcm_s16le", 16_000, 1)
    provider._ws = FakeWebSocket(
        [
            {
                "total_audio_proc_ms": 100,
                "tokens": [{"text": "Привет", "is_final": False, "confidence": 0.8}],
            },
            {
                "tokens": [
                    {"text": "Привет", "is_final": True, "confidence": 0.9},
                    {"text": " ", "is_final": True, "confidence": 0.9},
                    {"text": "мир", "is_final": True, "confidence": 0.9},
                    {"text": "<fin>", "is_final": True},
                ]
            },
        ]
    )

    events = [event async for event in provider.events()]
    finals = [event for event in events if isinstance(event, FinalizationComplete)]

    assert len(finals) == 1
    assert finals[0].text == "Привет мир"
    assert finals[0].confidence == 0.9
