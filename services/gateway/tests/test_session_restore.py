"""Переподключение не должно давать персонажа с амнезией."""

from ath_contracts import SessionStatus, StageExit, Turn, TurnRole
from ath_contracts.scenario import Persona, RubricItem, Scenario, Stage
from ath_contracts.session import SessionState, StageHistoryEntry

from app.orchestrator.session_manager import LiveSession


def _scenario() -> Scenario:
    return Scenario(
        id="objection_price",
        title="Возражение «дорого»",
        persona=Persona(name="Ирина", role="закупщик", character="скептична"),
        stages=[
            Stage(id="opening", goal="g", agent_opening="o", completion_criteria="c"),
            Stage(id="discovery", goal="g", agent_opening="o", completion_criteria="c"),
        ],
        rubric=[RubricItem(id="r", name="Критерий", description="d")],
    )


def _turn(role: TurnRole, text: str, stage_id: str) -> Turn:
    return Turn(role=role, text=text, stage_id=stage_id, ts=0.0)


def _state(**overrides) -> SessionState:
    base = {
        "session_id": "session",
        "scenario_id": "objection_price",
        "current_stage": "discovery",
        "current_gen": 7,
        "turns": [
            _turn(TurnRole.USER, "здравствуйте", "opening"),
            _turn(TurnRole.AGENT, "слушаю", "opening"),
            _turn(TurnRole.USER, "у нас дороже", "discovery"),
        ],
        "stage_history": [
            StageHistoryEntry(stage_id="opening", turns_spent=1, exit=StageExit.COMPLETE)
        ],
        "status": SessionStatus.ACTIVE,
    }
    return SessionState(**{**base, **overrides})


def test_adopt_restores_the_conversation() -> None:
    session = LiveSession(session_id="session", scenario=_scenario())
    session.adopt(_state())

    assert [turn.text for turn in session.turns] == ["здравствуйте", "слушаю", "у нас дороже"]
    assert session.current_stage_id == "discovery"
    assert [entry.stage_id for entry in session.stage_history] == ["opening"]


def test_generation_counter_continues_instead_of_restarting() -> None:
    session = LiveSession(session_id="session", scenario=_scenario())
    session.adopt(_state())

    # Если счётчик начать заново, gen_id из оборвавшегося соединения совпал бы
    # с новым, и уже отброшенный звук снова прошёл бы проверку на свежесть.
    assert session.generations.current == 7
    assert session.generations.bump() == 8


def test_turns_in_stage_counts_only_the_current_stage() -> None:
    session = LiveSession(session_id="session", scenario=_scenario())
    session.adopt(_state())

    # leave_stage() пишет turns_spent только на выходе, поэтому счётчик
    # текущего этапа восстанавливается по ходам, а не берётся из истории.
    assert session.turns_in_stage == 1


def test_restore_is_idempotent() -> None:
    session = LiveSession(session_id="session", scenario=_scenario())
    session.adopt(_state())
    session.adopt(_state())

    assert len(session.turns) == 3
    assert session.turns_in_stage == 1


def test_restored_session_keeps_running_its_stage_machine() -> None:
    session = LiveSession(session_id="session", scenario=_scenario())
    session.adopt(_state())

    session.leave_stage(StageExit.COMPLETE, "opening")

    assert [entry.stage_id for entry in session.stage_history] == ["opening", "discovery"]
    assert session.stage_history[-1].turns_spent == 1
    assert session.turns_in_stage == 0
