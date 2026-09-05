"""Инициативу держит агент — Claude.md §1, docs/agent-initiative.md.

Проверяется поведение конвейера, а не формулировки промптов (те живут в
ai-service): персонаж заговаривает сам в начале сессии и при смене этапа, а
счётчик уходов от темы доезжает до вызова реплики, не задевая автомат.

Дублёры клиентов и фикстуры — в conftest.py.
"""

import pytest
from ath_contracts import Classification, OpeningKind, Scenario, TurnRole

from app.orchestrator.session_manager import LiveSession
from tests.conftest import build_pipeline, drain


async def test_open_session_speaks_without_any_user_message(built) -> None:  # noqa: ANN001
    pipeline, session, ai, speech, _sent = built

    await pipeline.open_session()
    await drain(session)

    assert len(ai.reply_calls) == 1
    assert ai.reply_calls[0]["opening_kind"] is OpeningKind.SESSION_START
    assert speech.synthesized, "открывающая реплика должна дойти до TTS"

    # В истории ровно один ход, и он — от персонажа: человек ещё не говорил.
    assert [turn.role for turn in session.turns] == [TurnRole.AGENT]


async def test_stage_transition_opens_the_new_stage_in_the_same_turn(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Смена этапа не ждёт следующей реплики сотрудника."""
    session = LiveSession(session_id="s2", scenario=scenario)
    pipeline, ai, _speech, _sent = build_pipeline(session, monkeypatch)
    ai.classification = Classification.COMPLETE

    await pipeline.handle_user_message("Здравствуйте, я Пётр.", interrupts=None)
    await drain(session)

    assert len(ai.reply_calls) == 2, "ответ на реплику + открытие нового этапа"
    assert ai.reply_calls[0]["opening_kind"] is None
    assert ai.reply_calls[1]["opening_kind"] is OpeningKind.STAGE_TRANSITION
    assert session.current_stage_id == "discovery"
    # Открывающая реплика идёт тем же поколением — отдельного bump быть не должно.
    assert session.generations.current == 1


async def test_silence_followups_speak_without_fake_user_turns(built) -> None:  # noqa: ANN001
    pipeline, session, ai, _speech, _sent = built

    await pipeline.handle_silence_timeout("nudge", avatar_id="tom-avatar")
    await drain(session)
    await pipeline.handle_silence_timeout("continue", avatar_id="tom-avatar")
    await drain(session)

    assert [call["opening_kind"] for call in ai.reply_calls] == [
        OpeningKind.SILENCE_NUDGE,
        OpeningKind.SILENCE_CONTINUE,
    ]
    assert [turn.role for turn in session.turns] == [TurnRole.AGENT, TurnRole.AGENT]
    assert session.current_stage_id == session.machine.first_stage_id
    assert session.turns_in_stage == 0


async def test_off_topic_streak_grows_and_reaches_the_next_reply(built) -> None:  # noqa: ANN001
    pipeline, session, ai, _speech, _sent = built
    ai.classification = Classification.OFF_TOPIC

    await pipeline.handle_user_message("А что там с погодой?", interrupts=None)
    await drain(session)
    assert session.off_topic_streak == 1

    await pipeline.handle_user_message("И как ваш отпуск?", interrupts=None)
    await drain(session)
    assert session.off_topic_streak == 2

    # Реплика второго хода строилась уже со стриком первого — счётчик доезжает
    # до промпта без лишнего обращения к модели.
    assert ai.reply_calls[-1]["off_topic_streak"] == 1


async def test_stale_event_is_dropped_quietly(built) -> None:  # noqa: ANN001
    """Отброс чанка устаревшего поколения не должен падать — это метрика 4.

    Регрессия: в логировании этого пути стоял kwarg `event`, а у structlog так
    называется само сообщение. Любой реальный отброс ронял ход TypeError'ом
    вместо тихого игнорирования.

    setup_logging() здесь обязателен: без него structlog не настроен, debug не
    заглушается, и подмена на `_nop` — а с ней и падение — не воспроизводится.
    """
    pipeline, session, _ai, _speech, sent = built
    from ath_contracts import TokenEvent

    from app.core.logging import setup_logging

    setup_logging()

    session.generations.bump()
    session.generations.bump()  # текущее поколение = 2

    await pipeline._send(1, TokenEvent(gen_id=1, text="хвост"))

    assert sent == [], "устаревшее событие не должно уходить клиенту"


async def test_on_topic_answer_resets_the_streak(built) -> None:  # noqa: ANN001
    pipeline, session, ai, _speech, _sent = built
    ai.classification = Classification.OFF_TOPIC

    await pipeline.handle_user_message("Не по теме.", interrupts=None)
    await drain(session)
    assert session.off_topic_streak == 1

    ai.classification = Classification.INCOMPLETE
    await pipeline.handle_user_message("Вернулся к делу.", interrupts=None)
    await drain(session)

    assert session.off_topic_streak == 0
