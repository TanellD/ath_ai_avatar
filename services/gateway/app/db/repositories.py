"""Репозитории.

Обращения к БД идут только отсюда. Смысл прослойки не в абстракции ради
абстракции: она и есть та точка, где SQLite меняется на Postgres без правок в
оркестраторе. Протоколы объявлены явно, чтобы в тестах можно было подставить
in-memory реализацию, не поднимая базу.
"""

from typing import Protocol

from ath_contracts import Report, SessionState, Turn
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ReportRow, SessionRow, TurnRow, VoiceTurnCommitRow


class SessionRepository(Protocol):
    async def create(self, state: SessionState, user_id: str) -> None: ...
    async def get(self, session_id: str) -> SessionState | None: ...
    async def save_snapshot(self, state: SessionState) -> None: ...
    async def append_turn(self, session_id: str, index: int, turn: Turn, gen_id: int) -> None: ...
    async def commit_voice_turn(
        self, session_id: str, capture_id: str, index: int, turn: Turn, gen_id: int
    ) -> bool: ...


class ReportRepository(Protocol):
    async def save(self, report: Report) -> None: ...
    async def get(self, session_id: str) -> Report | None: ...


class SqlSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def create(self, state: SessionState, user_id: str) -> None:
        self._db.add(
            SessionRow(
                id=state.session_id,
                scenario_id=state.scenario_id,
                user_id=user_id,
                current_stage=state.current_stage,
                current_gen=state.current_gen,
                status=state.status.value,
                stage_history=[entry.model_dump(mode="json") for entry in state.stage_history],
            )
        )
        await self._db.commit()

    async def get(self, session_id: str) -> SessionState | None:
        row = await self._db.get(SessionRow, session_id)
        if row is None:
            return None

        turns = (
            await self._db.scalars(
                select(TurnRow).where(TurnRow.session_id == session_id).order_by(TurnRow.index)
            )
        ).all()

        return SessionState.model_validate(
            {
                "session_id": row.id,
                "scenario_id": row.scenario_id,
                "current_stage": row.current_stage,
                "current_gen": row.current_gen,
                "status": row.status,
                "stage_history": row.stage_history,
                "turns": [
                    {
                        "role": turn.role,
                        "text": turn.text,
                        "stage_id": turn.stage_id,
                        "ts": turn.ts,
                        "stt_confidence": turn.stt_confidence,
                        "audio_ref": turn.audio_ref,
                    }
                    for turn in turns
                ],
            }
        )

    async def save_snapshot(self, state: SessionState) -> None:
        """Сохранить изменившиеся поля сессии (без ходов — они пишутся отдельно)."""
        row = await self._db.get(SessionRow, state.session_id)
        if row is None:
            return
        row.current_stage = state.current_stage
        row.current_gen = state.current_gen
        row.status = state.status.value
        row.stage_history = [entry.model_dump(mode="json") for entry in state.stage_history]
        await self._db.commit()

    async def append_turn(self, session_id: str, index: int, turn: Turn, gen_id: int) -> None:
        self._db.add(
            TurnRow(
                session_id=session_id,
                index=index,
                role=turn.role.value,
                text=turn.text,
                stage_id=turn.stage_id,
                ts=turn.ts,
                stt_confidence=turn.stt_confidence,
                audio_ref=turn.audio_ref,
                gen_id=gen_id,
            )
        )
        await self._db.commit()

    async def commit_voice_turn(
        self, session_id: str, capture_id: str, index: int, turn: Turn, gen_id: int
    ) -> bool:
        """Атомарно записать voice turn; duplicate capture возвращает False."""
        existing = await self._db.get(
            VoiceTurnCommitRow, {"session_id": session_id, "capture_id": capture_id}
        )
        if existing is not None:
            return False

        self._db.add(
            VoiceTurnCommitRow(
                session_id=session_id,
                capture_id=capture_id,
                turn_index=index,
                gen_id=gen_id,
            )
        )
        self._db.add(
            TurnRow(
                session_id=session_id,
                index=index,
                role=turn.role.value,
                text=turn.text,
                stage_id=turn.stage_id,
                ts=turn.ts,
                stt_confidence=turn.stt_confidence,
                audio_ref=turn.audio_ref,
                gen_id=gen_id,
            )
        )
        try:
            await self._db.commit()
        except IntegrityError:
            await self._db.rollback()
            duplicate = await self._db.get(
                VoiceTurnCommitRow, {"session_id": session_id, "capture_id": capture_id}
            )
            if duplicate is not None:
                return False
            raise
        return True


class SqlReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def save(self, report: Report) -> None:
        self._db.add(
            ReportRow(
                session_id=report.session_id,
                verdict=report.verdict,
                total_score=report.total_score,
                payload=report.model_dump(mode="json"),
            )
        )
        await self._db.commit()

    async def get(self, session_id: str) -> Report | None:
        row = await self._db.get(ReportRow, session_id)
        return Report.model_validate(row.payload) if row else None
