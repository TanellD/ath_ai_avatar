"""Состояние сессии — Claude.md §7."""

from pydantic import BaseModel, Field

from ath_contracts.enums import SessionStatus, StageExit, TurnRole


class Turn(BaseModel):
    """Один ход диалога.

    В текстовой фазе `text` пользовательского хода — это ровно то, что человек
    напечатал, то есть истина. Поэтому `stt_confidence` и `audio_ref` всегда
    None: поля объявлены заранее, чтобы контракт отчёта не ломался при
    переходе на голос. См. docs/stt-phase.md.
    """

    role: TurnRole
    text: str
    stage_id: str
    ts: float = Field(description="Секунды от начала сессии")

    # [STT] Заполняются только при голосовом вводе.
    stt_confidence: float | None = None
    audio_ref: str | None = None


class StageHistoryEntry(BaseModel):
    stage_id: str
    turns_spent: int
    exit: StageExit


class SessionState(BaseModel):
    session_id: str
    scenario_id: str
    current_stage: str
    current_gen: int = Field(
        default=0,
        description="Счётчик поколений ответа. Растёт при каждом перебивании (§6)",
    )
    turns: list[Turn] = Field(default_factory=list)
    stage_history: list[StageHistoryEntry] = Field(default_factory=list)
    status: SessionStatus = SessionStatus.ACTIVE
