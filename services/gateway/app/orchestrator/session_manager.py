"""Живое состояние сессии — по одному объекту на WebSocket-соединение.

Состояние держится в памяти процесса: реплики и отчёт пишутся в SQLite, но
счётчик поколений и текущий этап живут здесь. Отсюда `--workers 1` в
Dockerfile. Когда воркеров станет больше одного, сюда встанет Redis (счётчик
поколений + pub/sub отмены) — интерфейс класса под это уже подходит.
"""

import time
from dataclasses import dataclass, field

from ath_contracts import (
    Scenario,
    SessionState,
    SessionStatus,
    StageExit,
    StageHistoryEntry,
    Turn,
    TurnRole,
)

from app.orchestrator.avatar_voice import DEFAULT_AVATAR_ID
from app.orchestrator.fsm import StageMachine
from app.orchestrator.generation import GenerationRegistry


@dataclass
class LiveSession:
    session_id: str
    scenario: Scenario
    avatar_id: str = DEFAULT_AVATAR_ID
    """Профиль аватара, выбранный учеником. Общий для текста и голоса."""
    generations: GenerationRegistry = field(default_factory=GenerationRegistry)
    started_at: float = field(default_factory=time.monotonic)

    current_stage_id: str = ""
    turns_in_stage: int = 0
    off_topic_streak: int = 0
    """Сколько реплик подряд классифицированы как off_topic. Влияет только на
    тон промпта персонажа (§1); автомат этапов об этом счётчике не знает и не
    должен — возврат в русло делает персонаж, а не fsm.py."""
    turns: list[Turn] = field(default_factory=list)
    stage_history: list[StageHistoryEntry] = field(default_factory=list)
    summary: str = ""
    summarized_through: int = 0
    """Сколько первых `turns` уже свёрнуты в `summary` (§5). Не путать с
    вытеснением из окна: ход вытесняется из видимости модели раньше, чем
    попадает сюда — этот счётчик двигает только сама суммаризация."""
    status: SessionStatus = SessionStatus.ACTIVE

    def __post_init__(self) -> None:
        self._machine = StageMachine(self.scenario)
        if not self.current_stage_id:
            self.current_stage_id = self._machine.first_stage_id

    @property
    def machine(self) -> StageMachine:
        return self._machine

    @property
    def elapsed_sec(self) -> int:
        return int(time.monotonic() - self.started_at)

    def add_turn(self, role: TurnRole, text: str) -> Turn:
        turn = self.make_turn(role, text)
        self.accept_turn(turn)
        return turn

    def make_turn(
        self,
        role: TurnRole,
        text: str,
        *,
        stt_confidence: float | None = None,
    ) -> Turn:
        return Turn(
            role=role,
            text=text,
            stage_id=self.current_stage_id,
            ts=time.monotonic() - self.started_at,
            stt_confidence=stt_confidence,
        )

    def accept_turn(self, turn: Turn) -> None:
        self.turns.append(turn)
        if turn.role is TurnRole.USER:
            self.turns_in_stage += 1

    def leave_stage(self, exit_reason: StageExit, next_stage_id: str) -> None:
        """Зафиксировать выход с этапа и перейти на следующий."""
        self.stage_history.append(
            StageHistoryEntry(
                stage_id=self.current_stage_id,
                turns_spent=self.turns_in_stage,
                exit=exit_reason,
            )
        )
        self.current_stage_id = next_stage_id
        self.turns_in_stage = 0
        self.off_topic_streak = 0

    def adopt(self, state: SessionState) -> None:
        """Поднять сохранённое состояние в память процесса.

        Ходы пишутся в БД сразу (`TurnPipeline._persist_turn`), поэтому при
        обрыве теряется только то, что живёт в памяти процесса: список ходов,
        история этапов и счётчик поколений. Без их восстановления
        переподключение даёт персонажа с амнезией.
        """
        self.current_stage_id = state.current_stage
        self.turns = list(state.turns)
        self.stage_history = list(state.stage_history)
        self.status = state.status
        self.generations.restore(state.current_gen)
        # Текущий этап в истории ещё не зафиксирован, его счётчик считаем по
        # ходам: leave_stage() пишет turns_spent только на выходе с этапа.
        self.turns_in_stage = sum(
            1
            for turn in self.turns
            if turn.role is TurnRole.USER and turn.stage_id == self.current_stage_id
        )

    def snapshot(self) -> SessionState:
        """Сериализуемое состояние — для персистентности и для GET /sessions/{id}."""
        return SessionState(
            session_id=self.session_id,
            scenario_id=self.scenario.id,
            current_stage=self.current_stage_id,
            current_gen=self.generations.current,
            turns=list(self.turns),
            stage_history=list(self.stage_history),
            status=self.status,
        )


class SessionRegistry:
    """Реестр активных сессий процесса."""

    def __init__(self) -> None:
        self._sessions: dict[str, LiveSession] = {}

    def create(self, session_id: str, scenario: Scenario) -> LiveSession:
        session = LiveSession(session_id=session_id, scenario=scenario)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> LiveSession | None:
        return self._sessions.get(session_id)

    async def drop(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is not None:
            await session.generations.cancel_all()
