"""Автомат этапов — Claude.md §5.

Проверяем главное: переход делает код по классификации, а не модель по своему
усмотрению. Свободная навигация даёт 20-30% преждевременных переходов, и
метрика 5 (≥ 4 корректно завершённых сценария из 5) держится именно здесь.
"""

import pytest
from ath_contracts import Action, Classification, Mood, StageExit
from ath_contracts.scenario import Persona, RubricItem, Scenario, Stage

from app.orchestrator.fsm import StageMachine


@pytest.fixture
def scenario() -> Scenario:
    return Scenario(
        id="objection_price",
        title="Отработка возражения «дорого»",
        persona=Persona(
            name="Ирина",
            role="закупщик среднего бизнеса",
            character="скептична, перебивает, торгуется",
            mood=Mood.NEUTRAL,
        ),
        stages=[
            Stage(
                id="opening",
                goal="Установить контакт",
                agent_opening="Здравствуйте.",
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


def test_complete_moves_to_next_stage(scenario: Scenario) -> None:
    machine = StageMachine(scenario)
    transition = machine.decide("opening", Classification.COMPLETE, turns_spent=1)

    assert transition.action is Action.NEXT_STAGE
    assert transition.next_stage_id == "discovery"
    assert transition.exit_reason is StageExit.COMPLETE


@pytest.mark.parametrize(
    "classification", [Classification.INCOMPLETE, Classification.OFF_TOPIC]
)
def test_incomplete_answer_stays_on_stage(
    scenario: Scenario, classification: Classification
) -> None:
    """Персонаж дожимает, а не пропускает этап — это и есть «не отходить от методики»."""
    machine = StageMachine(scenario)
    transition = machine.decide("opening", classification, turns_spent=1)

    assert transition.action is Action.STAY
    assert transition.next_stage_id == "opening"
    assert transition.exit_reason is None


def test_max_turns_forces_advance(scenario: Scenario) -> None:
    """Сотрудник не должен застревать на этапе бесконечно."""
    machine = StageMachine(scenario)
    transition = machine.decide("opening", Classification.INCOMPLETE, turns_spent=4)

    assert transition.action is Action.NEXT_STAGE
    assert transition.next_stage_id == "discovery"
    assert transition.exit_reason is StageExit.MAX_TURNS, (
        "методист обязан отличать «прошёл» от «дожали таймаутом»"
    )


def test_complete_on_last_stage_triggers_evaluation(scenario: Scenario) -> None:
    machine = StageMachine(scenario)
    transition = machine.decide("discovery", Classification.COMPLETE, turns_spent=2)

    assert transition.action is Action.EVALUATE
    assert transition.next_stage_id == "discovery", "с последнего этапа уходить некуда"


def test_max_turns_on_last_stage_also_triggers_evaluation(scenario: Scenario) -> None:
    machine = StageMachine(scenario)
    transition = machine.decide("discovery", Classification.OFF_TOPIC, turns_spent=3)

    assert transition.action is Action.EVALUATE
    assert transition.exit_reason is StageExit.MAX_TURNS


def test_first_stage_is_the_first_declared(scenario: Scenario) -> None:
    assert StageMachine(scenario).first_stage_id == "opening"
