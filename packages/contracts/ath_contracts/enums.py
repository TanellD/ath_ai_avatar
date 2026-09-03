"""Перечисления контрактов — Claude.md §5, §7."""

from enum import StrEnum


class Action(StrEnum):
    """Действие агента (Claude.md §3: минимум одно действие обязательно).

    Приходит от LLM вместе с репликой, но **решение о переходе принимает код**
    (см. gateway/app/orchestrator/fsm.py). Здесь — только словарь значений.
    """

    STAY = "stay"
    NEXT_STAGE = "next_stage"
    FINISH = "finish"
    EVALUATE = "evaluate"


class Classification(StrEnum):
    """Оценка полноты ответа пользователя — Claude.md §5.

    LLM классифицирует, автомат переходит. Свободная навигация даёт
    20-30% преждевременных переходов и нарушает методику заказчика.
    """

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    OFF_TOPIC = "off_topic"


class Mood(StrEnum):
    """Настроение персонажа. Варьируется между прогонами одного сценария —
    ответ на главную жалобу пользователей аналогов (Claude.md §7)."""

    NEUTRAL = "neutral"
    IRRITATED = "irritated"
    FRIENDLY = "friendly"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    FINISHED = "finished"
    ABANDONED = "abandoned"


class StageExit(StrEnum):
    """Как этап был покинут — попадает в stage_history."""

    COMPLETE = "complete"
    MAX_TURNS = "max_turns"
    SKIPPED = "skipped"


class TurnRole(StrEnum):
    USER = "user"
    AGENT = "agent"
