"""Общие дублёры конвейера.

Сеть в тестах конвейера не нужна — нужен порядок вызовов и состояние сессии,
поэтому клиенты ai/speech подменяются заглушками, а запись хода в БД
отключается. Живём здесь, а не в одном из тестовых модулей, потому что этим
пользуются и тесты инициативы, и тесты завершения.
"""

import asyncio
import base64
import io
import wave
from collections.abc import AsyncIterator

import pytest
from ath_contracts import (
    Classification,
    Emotion,
    Mood,
    Persona,
    Report,
    RubricItem,
    Scenario,
    Stage,
)
from ath_contracts.api import TtsChunk

from app.orchestrator.pipeline import TurnPipeline
from app.orchestrator.session_manager import LiveSession


@pytest.fixture
def scenario() -> Scenario:
    return Scenario(
        id="objection_price",
        title="Отработка возражения «дорого»",
        persona=Persona(
            name="Ирина",
            role="закупщик среднего бизнеса",
            character="скептична",
            mood=Mood.NEUTRAL,
        ),
        stages=[
            Stage(
                id="opening",
                goal="Установить контакт",
                agent_opening="Здравствуйте. У меня десять минут.",
                completion_criteria="Представился и задал открытый вопрос",
                max_turns=4,
            ),
            Stage(
                id="discovery",
                goal="Выявить потребность",
                agent_opening="И что вы предлагаете?",
                completion_criteria="Выяснил бюджет и сроки",
                max_turns=3,
            ),
        ],
        rubric=[RubricItem(id="discovery", name="Выявление потребности", description="...")],
    )


class FakeAi:
    """Записывает, с какими флагами звали реплику, и что классифицировал."""

    def __init__(self, classification: Classification = Classification.INCOMPLETE) -> None:
        self.reply_calls: list[dict] = []
        self.evaluate_calls: list[dict] = []
        self.classification = classification
        self.classify_error: Exception | None = None
        self.reply_text = "Слушаю вас."

    async def stream_character_reply(self, **kwargs) -> AsyncIterator[str]:
        self.reply_calls.append(kwargs)
        yield self.reply_text

    async def classify(self, stage, history, user_text) -> Classification:  # noqa: ANN001
        if self.classify_error is not None:
            raise self.classify_error
        return self.classification

    async def evaluate(self, **kwargs) -> Report:
        self.evaluate_calls.append(kwargs)
        return Report(
            session_id=kwargs["session_id"],
            verdict="Заглушка",
            total_score=3.0,
            scores=[],
            transcript=[],
            duration_sec=kwargs["duration_sec"],
            stages_completed=kwargs["stages_completed"],
            stages_total=kwargs["stages_total"],
        )


def silent_wav(duration_sec: float = 0.1, sample_rate: int = 24000) -> str:
    """Настоящий WAV: конвейер читает длительность из заголовка (§7)."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * round(duration_sec * sample_rate))
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class FakeSpeech:
    def __init__(self) -> None:
        self.synthesized: list[str] = []
        self.emotions: list[Emotion] = []

    async def stream_tts(
        self,
        gen_id: int,
        seq: int,
        text: str,
        voice_id: str | None,
        emotion: Emotion = Emotion.NEUTRAL,
    ) -> AsyncIterator[TtsChunk]:
        self.synthesized.append(text)
        self.emotions.append(emotion)
        yield TtsChunk(gen_id=gen_id, seq=seq, data=silent_wav(), is_final=True)

    async def stream_tts_reply(
        self,
        gen_id: int,
        seq: int,
        texts: AsyncIterator[str],
        voice_id: str | None,
        emotion: Emotion = Emotion.NEUTRAL,
    ) -> AsyncIterator[TtsChunk]:
        current_seq = seq
        async for text in texts:
            self.synthesized.append(text)
            self.emotions.append(emotion)
            yield TtsChunk(
                gen_id=gen_id,
                seq=current_seq,
                data=silent_wav(),
                is_final=False,
            )
            current_seq += 1


async def noop() -> None:
    return None


async def drain(session: LiveSession) -> None:
    """Дождаться задач поколения — конвейер запускает ход фоновой задачей."""
    registry = session.generations
    for tasks in list(registry._tasks.values()):
        for task in list(tasks):
            # Исключения хода здесь не интересны: тест смотрит на состояние
            # сессии и на то, чем звали клиентов, а не на способ завершения.
            await asyncio.gather(task, return_exceptions=True)


async def drain_background(pipeline: TurnPipeline) -> None:
    """Дождаться фоновых задач конвейера (запись хода, оценка).

    Оценка намеренно НЕ регистрируется в реестре поколений — иначе её убивал бы
    cancel_all() при закрытии сокета, — поэтому drain() её не видит."""
    for task in list(pipeline._background_tasks):
        await asyncio.gather(task, return_exceptions=True)


def build_pipeline(
    session: LiveSession, monkeypatch: pytest.MonkeyPatch
) -> tuple[TurnPipeline, FakeAi, FakeSpeech, list]:
    ai, speech, sent = FakeAi(), FakeSpeech(), []

    async def collect(event) -> None:  # noqa: ANN001
        sent.append(event)

    pipeline = TurnPipeline(
        session=session, ai=ai, speech=speech, send=collect, max_context_turns=6
    )
    # БД в этих тестах не участвует: проверяется поведение конвейера.
    monkeypatch.setattr(pipeline, "_persist_turn", lambda *a, **kw: noop())
    return pipeline, ai, speech, sent


@pytest.fixture
def built(scenario: Scenario, monkeypatch: pytest.MonkeyPatch):
    """Сессия + конвейер с дублёрами и отключённой записью в БД."""
    session = LiveSession(session_id="s1", scenario=scenario)
    pipeline, ai, speech, sent = build_pipeline(session, monkeypatch)
    return pipeline, session, ai, speech, sent
