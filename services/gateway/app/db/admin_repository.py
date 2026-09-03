"""Чтения для админ-панели — «путь сессии» и Gantt по конкретному ходу.

Отдельно от repositories.py намеренно: там — продуктовые контракты (§7),
здесь — внутренний инструмент отладки со своей формой данных (gen_id,
операционные спаны), которая наружу в ath_contracts не идёт. См.
docs/architecture.md, «Наблюдаемость».
"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SessionRow, SpanRow, TurnRow, UserRow


@dataclass
class SessionSummary:
    """Строка списка сессий на дашборде."""

    session_id: str
    scenario_id: str
    user_id: str
    user_display_name: str
    status: str
    current_stage: str
    turn_count: int
    created_at: str


@dataclass
class TurnRecord:
    """Один ход — со служебным gen_id, которого нет в публичном Turn (§7)."""

    index: int
    gen_id: int
    role: str
    text: str
    stage_id: str
    ts: float


@dataclass
class GenSummary:
    """Одно поколение («сообщение») сессии — для выбора перед Gantt-графиком."""

    gen_id: int
    preview: str
    span_count: int


@dataclass
class SpanRecord:
    gen_id: int
    seq: int
    operation: str
    label: str
    start_ms: int
    end_ms: int
    status: str
    error: str | None


@dataclass
class OperationLoad:
    """Нагрузка на один тип операции — «запросы к API» в разрезе дашборда.

    Каждая операция бьёт по конкретному downstream-сервису: character_reply
    и classify — вызовы ai-service, tts_synthesize — speech-service. spans
    уже несут это один-в-один (§ tracing.py), группировка ничего не
    домысливает."""

    operation: str
    service: str
    call_count: int
    avg_duration_ms: float
    p95_duration_ms: float
    error_count: int
    cancelled_count: int


@dataclass
class TimeBucket:
    """Один столбик графика активности — подпись HH:MM:SS, не дата.

    Дневная гранулярность бессмысленна для этого проекта: тестовые сессии
    идут пачками за минуты, а не размазаны по дням, — дневной бар-чарт
    почти всегда состоял бы из одного столбика «сегодня»."""

    label: str
    count: int


@dataclass
class LoadStats:
    operations: list[OperationLoad]
    sessions_total: int
    sessions_by_status: dict[str, int]
    sessions_timeline: list[TimeBucket]
    """Создания сессий, по бакетам."""
    activity_timeline: list[TimeBucket]
    """Операции конвейера (spans), по тем же бакетам — «сколько всего
    происходило» независимо от того, к какой сессии относится."""


_OPERATION_SERVICE = {
    "character_reply": "ai-service",
    "classify": "ai-service",
    "tts_synthesize": "speech-service",
}


def _percentile(sorted_values: list[int], p: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    if lo == hi:
        return float(sorted_values[lo])
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def _timeline(
    timestamps: list[datetime], since: datetime, until: datetime, bucket_seconds: int
) -> list[TimeBucket]:
    """Считает бакеты в Python, а не в SQL — тот же довод, что и у p95:
    датасет мал, а `strftime` с произвольным шагом в секундах на диалект-
    независимом SQL был бы сложнее этого цикла. Бакеты нулевые заполняются
    явно, иначе пустые интервалы просто выпадают из графика и он врёт
    формой — выглядит как «активности не было», хотя на деле это «не было
    события ровно на границе бакета»."""
    bucket_span = timedelta(seconds=bucket_seconds)
    first_bucket = since - timedelta(seconds=since.timestamp() % bucket_seconds)
    counts: Counter[datetime] = Counter()
    for ts in timestamps:
        offset = (ts - first_bucket).total_seconds()
        bucket_index = int(offset // bucket_seconds)
        counts[first_bucket + bucket_index * bucket_span] += 1

    buckets = []
    cursor = first_bucket
    while cursor <= until:
        buckets.append(TimeBucket(label=cursor.strftime("%H:%M:%S"), count=counts.get(cursor, 0)))
        cursor += bucket_span
    return buckets


class AdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def list_sessions(self, limit: int = 100) -> list[SessionSummary]:
        turn_counts = (
            select(TurnRow.session_id, func.count(TurnRow.id).label("n"))
            .group_by(TurnRow.session_id)
            .subquery()
        )
        rows = (
            await self._db.execute(
                select(SessionRow, turn_counts.c.n, UserRow.display_name)
                .outerjoin(turn_counts, turn_counts.c.session_id == SessionRow.id)
                .outerjoin(UserRow, UserRow.id == SessionRow.user_id)
                .order_by(SessionRow.created_at.desc())
                .limit(limit)
            )
        ).all()

        return [
            SessionSummary(
                session_id=row.SessionRow.id,
                scenario_id=row.SessionRow.scenario_id,
                user_id=row.SessionRow.user_id,
                user_display_name=row.display_name or row.SessionRow.user_id,
                status=row.SessionRow.status,
                current_stage=row.SessionRow.current_stage,
                turn_count=row.n or 0,
                created_at=row.SessionRow.created_at.isoformat(),
            )
            for row in rows
        ]

    async def get_session_path(
        self, session_id: str
    ) -> tuple[SessionSummary, list[TurnRecord]] | None:
        """«Путь сессии»: сводка + все ходы по порядку, с их gen_id и этапом."""
        row = await self._db.get(SessionRow, session_id)
        if row is None:
            return None

        user = await self._db.get(UserRow, row.user_id)
        turn_rows = (
            await self._db.scalars(
                select(TurnRow).where(TurnRow.session_id == session_id).order_by(TurnRow.index)
            )
        ).all()

        summary = SessionSummary(
            session_id=row.id,
            scenario_id=row.scenario_id,
            user_id=row.user_id,
            user_display_name=user.display_name if user else row.user_id,
            status=row.status,
            current_stage=row.current_stage,
            turn_count=len(turn_rows),
            created_at=row.created_at.isoformat(),
        )
        turns = [
            TurnRecord(
                index=t.index,
                gen_id=t.gen_id,
                role=t.role,
                text=t.text,
                stage_id=t.stage_id,
                ts=t.ts,
            )
            for t in turn_rows
        ]
        return summary, turns

    async def list_gens(self, session_id: str) -> list[GenSummary]:
        """Поколения сессии — по одному на отправленную сотрудником реплику,
        с превью для выпадающего списка в UI."""
        turn_rows = (
            await self._db.scalars(
                select(TurnRow)
                .where(TurnRow.session_id == session_id, TurnRow.role == "user")
                .order_by(TurnRow.gen_id)
            )
        ).all()

        span_counts = dict(
            (
                await self._db.execute(
                    select(SpanRow.gen_id, func.count(SpanRow.id))
                    .where(SpanRow.session_id == session_id)
                    .group_by(SpanRow.gen_id)
                )
            ).all()
        )

        return [
            GenSummary(
                gen_id=t.gen_id,
                preview=t.text[:80],
                span_count=span_counts.get(t.gen_id, 0),
            )
            for t in turn_rows
        ]

    async def list_spans(self, session_id: str, gen_id: int) -> list[SpanRecord]:
        rows = (
            await self._db.scalars(
                select(SpanRow)
                .where(SpanRow.session_id == session_id, SpanRow.gen_id == gen_id)
                .order_by(SpanRow.seq)
            )
        ).all()
        return [
            SpanRecord(
                gen_id=row.gen_id,
                seq=row.seq,
                operation=row.operation,
                label=row.label,
                start_ms=row.start_ms,
                end_ms=row.end_ms,
                status=row.status,
                error=row.error,
            )
            for row in rows
        ]

    async def get_load_stats(self, minutes: int = 30, bucket_seconds: int = 30) -> LoadStats:
        """Агрегаты для дашборда нагрузки: сколько вызовов к какому API,
        сколько сессий и когда. Процентиль и тайм-бакеты считаются в
        Python — датасет этого проекта не настолько велик, чтобы городить
        оконные функции/диалект-специфичный `strftime` под шаг в секундах,
        а переезд на Postgres эту функцию не поменяет (см. docs/data.md).

        Таймлайны — за последние `minutes` минут, бакетами по
        `bucket_seconds`: дневная гранулярность здесь бессмысленна, тестовые
        сессии идут пачками за минуты, а не размазаны по дням."""
        span_rows = (
            await self._db.execute(
                select(
                    SpanRow.operation, SpanRow.start_ms, SpanRow.end_ms, SpanRow.status,
                    SpanRow.created_at,
                )
            )
        ).all()

        by_operation: dict[str, list[tuple[int, str]]] = {}
        for operation, start_ms, end_ms, status, _created_at in span_rows:
            by_operation.setdefault(operation, []).append((end_ms - start_ms, status))

        operations = []
        for operation, entries in sorted(by_operation.items()):
            durations = sorted(d for d, _ in entries)
            error_count = sum(1 for _, s in entries if s == "error")
            cancelled_count = sum(1 for _, s in entries if s == "cancelled")
            operations.append(
                OperationLoad(
                    operation=operation,
                    service=_OPERATION_SERVICE.get(operation, "unknown"),
                    call_count=len(entries),
                    avg_duration_ms=round(sum(durations) / len(durations), 1) if durations else 0.0,
                    p95_duration_ms=round(_percentile(durations, 0.95), 1),
                    error_count=error_count,
                    cancelled_count=cancelled_count,
                )
            )

        sessions_total = await self._db.scalar(select(func.count(SessionRow.id))) or 0

        status_rows = (
            await self._db.execute(
                select(SessionRow.status, func.count(SessionRow.id)).group_by(SessionRow.status)
            )
        ).all()
        sessions_by_status = dict(status_rows)

        until = datetime.utcnow()
        since = until - timedelta(minutes=minutes)

        session_times = (
            await self._db.scalars(
                select(SessionRow.created_at).where(SessionRow.created_at >= since)
            )
        ).all()
        span_times = [created_at for *_rest, created_at in span_rows if created_at >= since]

        return LoadStats(
            operations=operations,
            sessions_total=sessions_total,
            sessions_by_status=sessions_by_status,
            sessions_timeline=_timeline(list(session_times), since, until, bucket_seconds),
            activity_timeline=_timeline(span_times, since, until, bucket_seconds),
        )
