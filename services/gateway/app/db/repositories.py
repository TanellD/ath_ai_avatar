"""Репозитории.

Обращения к БД идут только отсюда. Смысл прослойки не в абстракции ради
абстракции: она и есть та точка, где SQLite меняется на Postgres без правок в
оркестраторе. Протоколы объявлены явно, чтобы в тестах можно было подставить
in-memory реализацию, не поднимая базу.
"""

from datetime import UTC, datetime
from typing import Protocol

from ath_contracts import Report, SessionState, SessionStatus, Turn
from ath_contracts.api import SessionSummaryItem
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ReportRow, SessionRow, TurnRow


class SessionRepository(Protocol):
    async def create(self, state: SessionState, user_id: str) -> None: ...
    async def get(self, session_id: str) -> SessionState | None: ...
    async def save_snapshot(self, state: SessionState) -> None: ...
    async def mark_finished(self, session_id: str) -> None: ...
    async def list_summaries(self, limit: int = 100) -> list[SessionSummaryItem]: ...
    async def append_turn(self, session_id: str, index: int, turn: Turn, gen_id: int) -> None: ...


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

    async def list_summaries(self, limit: int = 100) -> list[SessionSummaryItem]:
        """Сессии для экрана методиста (§2), новые сверху.

        Пустые сессии отфильтрованы (`join`, а не `outerjoin`, по счётчику
        ходов): до недавнего времени строка заводилась на каждый заход на
        страницу тренировки, и таких в базе накопилось больше, чем настоящих.
        Тренировка без единого хода методисту не нужна ни для чего — ни
        истории, ни оценки в ней нет.
        """
        turn_counts = (
            select(TurnRow.session_id, func.count(TurnRow.id).label("n"))
            .group_by(TurnRow.session_id)
            .subquery()
        )
        rows = (
            await self._db.execute(
                select(SessionRow, turn_counts.c.n, ReportRow.session_id.label("report_id"))
                .join(turn_counts, turn_counts.c.session_id == SessionRow.id)
                .outerjoin(ReportRow, ReportRow.session_id == SessionRow.id)
                .order_by(SessionRow.created_at.desc())
                .limit(limit)
            )
        ).all()

        return [
            SessionSummaryItem(
                session_id=row.SessionRow.id,
                scenario_id=row.SessionRow.scenario_id,
                status=SessionStatus(row.SessionRow.status),
                turn_count=row.n,
                created_at=row.SessionRow.created_at.isoformat(),
                finished_at=(
                    row.SessionRow.finished_at.isoformat()
                    if row.SessionRow.finished_at
                    else None
                ),
                has_report=row.report_id is not None,
            )
            for row in rows
        ]

    async def mark_finished(self, session_id: str) -> None:
        """Зафиксировать завершение: статус и время окончания.

        Отдельно от save_snapshot: снимок делается на дисконнекте, а завершение
        надо записать в момент, когда оно произошло, — иначе сессия, из которой
        сотрудник ушёл сразу после финала, останется в БД как active.
        """
        row = await self._db.get(SessionRow, session_id)
        if row is None:
            return
        row.status = SessionStatus.FINISHED.value
        row.finished_at = datetime.now(UTC).replace(tzinfo=None)
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


class SqlReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def save(self, report: Report) -> None:
        """Сохранить или перезаписать отчёт.

        Именно перезаписать, а не только вставить: оценку можно запустить
        повторно (POST /sessions/{id}/report), когда первая прошла на заглушке
        или упала. Простой INSERT падал бы на дубликате первичного ключа, и
        «пересчитать» работало бы ровно один раз — то есть никогда.
        """
        row = await self._db.get(ReportRow, report.session_id)
        if row is None:
            row = ReportRow(session_id=report.session_id)
            self._db.add(row)

        row.verdict = report.verdict
        row.total_score = report.total_score
        row.payload = report.model_dump(mode="json")
        await self._db.commit()

    async def get(self, session_id: str) -> Report | None:
        row = await self._db.get(ReportRow, session_id)
        return Report.model_validate(row.payload) if row else None
