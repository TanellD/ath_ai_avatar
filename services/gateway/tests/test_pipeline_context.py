"""Регресс: «теряется контекст, когда сообщений становится больше».

С окном в несколько ходов и достаточно длинным разговором ранние реплики
раньше просто отваливались из того, что видит модель, без всякого следа —
session.summary заводился в контракте, но ничего его не заполняло. Здесь
проверяется, что каждый вытесненный ход рано или поздно попадает в вызов
ai.summarize(), без пропусков и без повторной отправки одного и того же
хода дважды.
"""

import pytest
from ath_contracts import Scenario

from app.orchestrator.session_manager import LiveSession
from tests.conftest import build_pipeline, drain


async def test_evicted_turns_all_get_folded_into_the_summary(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = LiveSession(session_id="s-context", scenario=scenario)
    pipeline, ai, _speech, _sent = build_pipeline(session, monkeypatch)  # max_context_turns=6

    for i in range(6):
        await pipeline.handle_user_message(f"Реплика сотрудника номер {i}", interrupts=None)
        await drain(session)

    assert len(session.turns) > 6, "тест бессмыслен, если окно ни разу не переполнилось"
    assert ai.summarize_calls, "окно переполнилось, но ни один ход не ушёл в суммаризацию"

    # Все вытесненные партии подряд, без пропуска и без повторной отправки
    # одного и того же хода — иначе часть истории либо теряется молча
    # (пропуск), либо оплачивается дважды (повтор).
    covered = [turn for call in ai.summarize_calls for turn in call["evicted"]]
    assert covered == session.turns[: session.summarized_through]

    # Выжимка реально обновилась, а не осталась пустой заглушкой.
    assert session.summary
