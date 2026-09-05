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


class OpeningKind(StrEnum):
    """Зачем персонаж заговорил сам, без реплики пользователя.

    Инициативу держит агент (Claude.md §1), поэтому он открывает и сессию, и
    каждый новый этап. Два случая различаются ровно одним: в начале сессии
    персонаж представляется, при переходе между этапами — уже нет.
    """

    SESSION_START = "session_start"
    STAGE_TRANSITION = "stage_transition"


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
