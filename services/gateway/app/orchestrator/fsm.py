"""Конечный автомат этапов — Claude.md §5.

**LLM не решает, куда двигаться.** Она классифицирует ответ пользователя как
`complete | incomplete | off_topic`, а переход делает код — вот этот файл.

Причина из постановки: требование заказчика не отходить от методики. Свободная
навигация даёт 20-30% преждевременных переходов.

Файл реализован целиком, а не заглушкой: он маленький, и именно на нём держится
метрика 5 (корректно завершённые сценарии ≥ 4 из 5).
"""

from dataclasses import dataclass

from ath_contracts import Action, Classification, Scenario, StageExit

from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class Transition:
    """Результат решения автомата."""

    action: Action
    next_stage_id: str
    exit_reason: StageExit | None = None
    """Заполнен только когда этап действительно покидается — идёт в stage_history."""


class StageMachine:
    """Автомат этапов одного сценария.

    Состояние снаружи: `current_stage_id` и `turns_spent`. Хранить его внутри
    сессии, а не здесь, чтобы автомат оставался чистой функцией от входа.
    """

    def __init__(self, scenario: Scenario) -> None:
        self._scenario = scenario
        self._order = [stage.id for stage in scenario.stages]
        self._by_id = {stage.id: stage for stage in scenario.stages}

    @property
    def first_stage_id(self) -> str:
        return self._order[0]

    def stage(self, stage_id: str):  # -> Stage
        return self._by_id[stage_id]

    def decide(
        self,
        current_stage_id: str,
        classification: Classification,
        turns_spent: int,
    ) -> Transition:
        """Решить, что делать после хода пользователя.

        Правила, в порядке приоритета:

        1. `complete` — этап пройден, идём дальше; на последнем этапе завершаем.
        2. Исчерпан `max_turns` — уходим дальше принудительно, чтобы сотрудник
           не застревал; в истории это помечается как `max_turns`, и методист
           видит разницу между «прошёл» и «дожали таймаутом».
        3. `incomplete` / `off_topic` — остаёмся, персонаж дожимает.

        `off_topic` намеренно не наказывается отдельной веткой: возврат в
        русло — работа персонажа, а не автомата.
        """
        stage = self._by_id[current_stage_id]

        if classification is Classification.COMPLETE:
            return self._advance(current_stage_id, StageExit.COMPLETE)

        if turns_spent >= stage.max_turns:
            log.info(
                "fsm.max_turns_exceeded",
                stage_id=current_stage_id,
                turns_spent=turns_spent,
                max_turns=stage.max_turns,
            )
            return self._advance(current_stage_id, StageExit.MAX_TURNS)

        return Transition(action=Action.STAY, next_stage_id=current_stage_id)

    def _advance(self, current_stage_id: str, exit_reason: StageExit) -> Transition:
        index = self._order.index(current_stage_id)
        is_last = index == len(self._order) - 1

        if is_last:
            # Последний этап пройден — сценарий окончен, дальше идёт оценка.
            return Transition(
                action=Action.EVALUATE,
                next_stage_id=current_stage_id,
                exit_reason=exit_reason,
            )

        return Transition(
            action=Action.NEXT_STAGE,
            next_stage_id=self._order[index + 1],
            exit_reason=exit_reason,
        )
