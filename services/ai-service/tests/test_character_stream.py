"""stream_character_reply — реплика персонажа как SSE-события.

Живой баг на думающей локальной модели (qwen3.6:35b, отчёт «Наладка
локальной модели», 07.09.2026): рассуждение съедало весь `max_tokens`
(`finish_reason: "length"`), `content` приходил пустым — персонаж молча не
отвечал, ни строчки в логе. `reasoning_effort=none` и `_strip_inline_reasoning`
(см. `test_openai_compatible_reasoning_filter.py`) закрывают известные
причины утечки рассуждения в content, но не гарантируют, что пустая реплика
больше никогда не случится на каком-то ещё не встреченном провайдере —
поэтому важно, чтобы такой случай хотя бы был виден в логах.
"""

from collections.abc import AsyncIterator

import pytest
import structlog.testing
from ath_contracts import Emotion

from app.api.character import stream_character_reply
from app.llm.base import LlmProvider


class _FakeProvider(LlmProvider):
    """Провайдер, отдающий заранее заданные токены content-стрима."""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    @property
    def name(self) -> str:
        return "fake"

    async def aclose(self) -> None:
        pass

    async def stream(self, **_kwargs: object) -> AsyncIterator[str]:
        for token in self._tokens:
            yield token

    async def complete_json(self, **_kwargs: object) -> dict:
        raise NotImplementedError


async def _collect_events(provider: LlmProvider) -> list[dict[str, str]]:
    return [
        event
        async for event in stream_character_reply(
            provider=provider,
            system="система",
            messages=[{"role": "user", "text": "Привет"}],
            model="qwen3.6:35b",
            max_tokens=300,
            temperature=0.8,
            fallback=Emotion.NEUTRAL,
        )
    ]


@pytest.mark.anyio
async def test_normal_reply_has_no_warning() -> None:
    with structlog.testing.capture_logs() as logs:
        events = await _collect_events(_FakeProvider(["Здравствуйте", ", как дела?"]))

    done = next(e for e in events if e["event"] == "done")
    assert "Здравствуйте, как дела?" in done["data"]
    assert not any(entry["event"] == "character.empty_reply" for entry in logs)


@pytest.mark.anyio
async def test_empty_reply_is_logged_as_warning() -> None:
    """Ровно живой случай: рассуждение съело весь бюджет, content пуст."""
    with structlog.testing.capture_logs() as logs:
        events = await _collect_events(_FakeProvider([]))

    done = next(e for e in events if e["event"] == "done")
    assert '"full_text":""' in done["data"]

    warnings = [entry for entry in logs if entry["event"] == "character.empty_reply"]
    assert len(warnings) == 1
    assert warnings[0]["log_level"] == "warning"
    assert warnings[0]["model"] == "qwen3.6:35b"
    assert warnings[0]["max_tokens"] == 300


@pytest.mark.anyio
async def test_reply_that_is_only_an_emotion_marker_counts_as_empty() -> None:
    """Эмоциональный маркер съедается парсером и не идёт в full_text — если
    после него больше ничего нет, это тоже пустая реплика, а не молчаливый
    успех."""
    with structlog.testing.capture_logs() as logs:
        events = await _collect_events(_FakeProvider(["<emotion=irritated>"]))

    done = next(e for e in events if e["event"] == "done")
    assert '"full_text":""' in done["data"]
    assert any(entry["event"] == "character.empty_reply" for entry in logs)
