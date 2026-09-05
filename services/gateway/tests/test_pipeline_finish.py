"""Завершение тренировки — Claude.md §3 («завершить», «сформировать оценку»).

До этой работы `Action.EVALUATE` из автомата никто не потреблял: сессия
оставалась active навсегда, отчёт не появлялся. Здесь проверяется, что оба
триггера (автомат и кнопка сотрудника) доводят дело до оценки, и ровно один
раз.

Отдельно — два бага, найденных на живой сессии: устаревшее поколение писало
реплику-призрак в транскрипт, а сбой классификации отключал автомат на ход.
"""

import pytest
from ath_contracts import Action, Classification, Scenario, SessionStatus, TurnRole

from app.orchestrator.session_manager import LiveSession
from tests.conftest import build_pipeline, drain, drain_background, noop


@pytest.fixture
def finishing(scenario: Scenario, monkeypatch: pytest.MonkeyPatch):
    """Сессия на ПОСЛЕДНЕМ этапе — следующий complete завершает сценарий."""
    session = LiveSession(session_id="s-finish", scenario=scenario)
    session.current_stage_id = scenario.stages[-1].id
    pipeline, ai, speech, sent = build_pipeline(session, monkeypatch)
    # Запись факта завершения в БД проверяется отдельно, здесь БД не поднята.
    monkeypatch.setattr(pipeline, "_mark_finished", lambda: noop())
    return pipeline, session, ai, speech, sent


async def test_evaluate_action_finishes_session(finishing) -> None:  # noqa: ANN001
    """Пройден последний этап — сессия завершается и уходит на оценку."""
    pipeline, session, ai, _speech, sent = finishing
    ai.classification = Classification.COMPLETE

    await pipeline.handle_user_message("Спасибо, договорились.", interrupts=None)
    await drain(session)
    await drain_background(pipeline)

    assert session.status is SessionStatus.FINISHED
    assert len(ai.evaluate_calls) == 1, "оценка должна запуститься ровно один раз"

    finish_events = [e for e in sent if e.type == "action" and e.action is Action.FINISH]
    assert len(finish_events) == 1, "клиенту нужен сигнал поднять финальный оверлей"


async def test_evaluate_gets_real_session_numbers(finishing) -> None:  # noqa: ANN001
    """В оценку уходит фактический транскрипт и счётчики этапов (§7)."""
    pipeline, session, ai, _speech, _sent = finishing
    ai.classification = Classification.COMPLETE

    await pipeline.handle_user_message("Спасибо, договорились.", interrupts=None)
    await drain(session)
    await drain_background(pipeline)

    call = ai.evaluate_calls[0]
    assert call["session_id"] == session.session_id
    assert call["stages_total"] == len(session.scenario.stages)
    assert [t.role for t in call["transcript"]] == [TurnRole.USER, TurnRole.AGENT]


async def test_finish_is_idempotent(finishing) -> None:  # noqa: ANN001
    """Кнопка и автомат могут сработать вместе, кнопку можно нажать дважды."""
    pipeline, session, ai, _speech, _sent = finishing

    await pipeline.handle_finish_request()
    await pipeline.handle_finish_request()
    await drain_background(pipeline)

    assert session.status is SessionStatus.FINISHED
    assert len(ai.evaluate_calls) == 1, "второе завершение не должно оценивать заново"


async def test_manual_finish_cancels_active_reply(built) -> None:  # noqa: ANN001
    """Персонаж мог говорить в момент нажатия — реплику надо снять."""
    pipeline, session, _ai, _speech, _sent = built

    await pipeline.open_session()
    assert session.generations.current == 1

    await pipeline.handle_finish_request()
    await drain_background(pipeline)

    assert session.status is SessionStatus.FINISHED
    assert not session.generations._tasks, "активных задач поколения остаться не должно"


# --------------------------------------------------- баги с живой сессии


async def test_stale_generation_does_not_persist_turn(built) -> None:  # noqa: ANN001
    """Реплика устаревшего поколения не попадает в транскрипт.

    Живой случай: открывающая реплика генерировалась 30 с, пользователь успел
    отправить новое сообщение, `_send` погасил звук — сотрудник её не слышал,
    но ход всё равно записывался, да ещё и с чужим этапом. А транскрипт
    целиком уходит в оценку методисту.
    """
    pipeline, session, _ai, _speech, _sent = built

    session.generations.bump()  # поколение 1 — «наше»
    session.generations.bump()  # поколение 2 — пришло, пока мы говорили

    await pipeline._record_agent_turn(1, "хвост устаревшей реплики")

    assert session.turns == [], "устаревшую реплику записывать нельзя"


async def test_fresh_generation_still_persists_turn(built) -> None:  # noqa: ANN001
    """Обратная сторона предыдущего теста: актуальная реплика записывается."""
    pipeline, session, _ai, _speech, _sent = built

    session.generations.bump()
    await pipeline._record_agent_turn(1, "нормальная реплика")

    assert [t.text for t in session.turns] == ["нормальная реплика"]


async def test_classify_failure_still_advances_on_max_turns(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сбой классификации не имеет права останавливать сценарий.

    Живой случай: два подряд таймаута classify (по 30 с) — исключение уходило
    наверх, decide() не вызывался, и принудительный переход по max_turns не
    срабатывал. Этап перешагнул лимит на два хода, сценарий не дошёл до финала.
    """
    session = LiveSession(session_id="s-classify", scenario=scenario)
    pipeline, ai, _speech, _sent = build_pipeline(session, monkeypatch)
    ai.classify_error = RuntimeError("classify timed out")

    stage = session.machine.stage(session.current_stage_id)
    for i in range(stage.max_turns):
        await pipeline.handle_user_message(f"Реплика {i}.", interrupts=None)
        await drain(session)

    assert session.current_stage_id != stage.id, (
        "max_turns обязан сработать даже когда классификатор недоступен"
    )
