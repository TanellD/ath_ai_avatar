"""Админ-панель — наблюдаемость, не продукт.

Список сессий, «путь» одной сессии (этапы + ходы) и Gantt-данные по
конкретному ходу (gen_id = «id сообщения»: по одному на каждую реплику
сотрудника). Не часть §7 — внутренний инструмент для отладки конвейера,
поэтому модели ответа объявлены прямо здесь, а не в ath_contracts (см.
app/db/admin_repository.py).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.admin_repository import AdminRepository
from app.db.engine import get_session

router = APIRouter(prefix="/admin", tags=["admin"])


class SessionSummaryResponse(BaseModel):
    session_id: str
    scenario_id: str
    user_id: str
    user_display_name: str
    status: str
    current_stage: str
    turn_count: int
    created_at: str


class SessionListResponse(BaseModel):
    items: list[SessionSummaryResponse]


class TurnResponse(BaseModel):
    index: int
    gen_id: int
    role: str
    text: str
    stage_id: str
    ts: float


class SessionPathResponse(BaseModel):
    session: SessionSummaryResponse
    turns: list[TurnResponse]


class GenSummaryResponse(BaseModel):
    gen_id: int
    preview: str
    span_count: int


class GenListResponse(BaseModel):
    items: list[GenSummaryResponse]


class SpanResponse(BaseModel):
    gen_id: int
    seq: int
    operation: str
    label: str
    start_ms: int
    end_ms: int
    status: str
    error: str | None


class SpanListResponse(BaseModel):
    items: list[SpanResponse]


class OperationLoadResponse(BaseModel):
    operation: str
    service: str
    call_count: int
    avg_duration_ms: float
    p95_duration_ms: float
    error_count: int
    cancelled_count: int


class TimeBucketResponse(BaseModel):
    label: str
    count: int


class LoadResponse(BaseModel):
    operations: list[OperationLoadResponse]
    sessions_total: int
    sessions_by_status: dict[str, int]
    sessions_timeline: list[TimeBucketResponse]
    activity_timeline: list[TimeBucketResponse]


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(db: AsyncSession = Depends(get_session)) -> SessionListResponse:
    """Дашборд: все сессии, новые сверху."""
    rows = await AdminRepository(db).list_sessions()
    return SessionListResponse(
        items=[
            SessionSummaryResponse(
                session_id=r.session_id,
                scenario_id=r.scenario_id,
                user_id=r.user_id,
                user_display_name=r.user_display_name,
                status=r.status,
                current_stage=r.current_stage,
                turn_count=r.turn_count,
                created_at=r.created_at,
            )
            for r in rows
        ]
    )


@router.get("/sessions/{session_id}/path", response_model=SessionPathResponse)
async def get_session_path(
    session_id: str, db: AsyncSession = Depends(get_session)
) -> SessionPathResponse:
    """«Путь сессии» — все ходы по порядку, с gen_id и этапом каждого."""
    result = await AdminRepository(db).get_session_path(session_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")

    summary, turns = result
    return SessionPathResponse(
        session=SessionSummaryResponse(
            session_id=summary.session_id,
            scenario_id=summary.scenario_id,
            user_id=summary.user_id,
            user_display_name=summary.user_display_name,
            status=summary.status,
            current_stage=summary.current_stage,
            turn_count=summary.turn_count,
            created_at=summary.created_at,
        ),
        turns=[
            TurnResponse(
                index=t.index, gen_id=t.gen_id, role=t.role, text=t.text,
                stage_id=t.stage_id, ts=t.ts,
            )
            for t in turns
        ],
    )


@router.get("/sessions/{session_id}/gens", response_model=GenListResponse)
async def list_gens(session_id: str, db: AsyncSession = Depends(get_session)) -> GenListResponse:
    """Поколения («сообщения») сессии — выбрать одно перед Gantt-графиком."""
    rows = await AdminRepository(db).list_gens(session_id)
    return GenListResponse(
        items=[
            GenSummaryResponse(gen_id=r.gen_id, preview=r.preview, span_count=r.span_count)
            for r in rows
        ]
    )


@router.get("/sessions/{session_id}/gens/{gen_id}/spans", response_model=SpanListResponse)
async def list_spans(
    session_id: str, gen_id: int, db: AsyncSession = Depends(get_session)
) -> SpanListResponse:
    """Данные для Gantt-графика одного хода."""
    rows = await AdminRepository(db).list_spans(session_id, gen_id)
    return SpanListResponse(
        items=[
            SpanResponse(
                gen_id=r.gen_id, seq=r.seq, operation=r.operation, label=r.label,
                start_ms=r.start_ms, end_ms=r.end_ms, status=r.status, error=r.error,
            )
            for r in rows
        ]
    )


@router.get("/load", response_model=LoadResponse)
async def get_load(db: AsyncSession = Depends(get_session)) -> LoadResponse:
    """Нагрузка: сколько вызовов ушло в какой downstream-сервис, с какой
    латентностью и как часто с ошибкой, плюс сессии/активность по времени
    (бакеты HH:MM:SS за последние get_load_stats.minutes минут — дневная
    гранулярность бессмысленна на масштабе этого проекта)."""
    stats = await AdminRepository(db).get_load_stats()
    return LoadResponse(
        operations=[
            OperationLoadResponse(
                operation=o.operation, service=o.service, call_count=o.call_count,
                avg_duration_ms=o.avg_duration_ms, p95_duration_ms=o.p95_duration_ms,
                error_count=o.error_count, cancelled_count=o.cancelled_count,
            )
            for o in stats.operations
        ],
        sessions_total=stats.sessions_total,
        sessions_by_status=stats.sessions_by_status,
        sessions_timeline=[
            TimeBucketResponse(label=b.label, count=b.count) for b in stats.sessions_timeline
        ],
        activity_timeline=[
            TimeBucketResponse(label=b.label, count=b.count) for b in stats.activity_timeline
        ],
    )
