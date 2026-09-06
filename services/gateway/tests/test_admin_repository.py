"""Круговой тест AdminRepository: пишем через продуктовые репозитории и
SpanRow напрямую, читаем через админ-чтения. In-memory SQLite, без Docker.
"""

from collections.abc import AsyncIterator

import pytest
from ath_contracts import Report, SessionState, StageExit, StageHistoryEntry, Turn, TurnRole
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.admin_repository import AdminRepository
from app.db.models import Base, ReportRow, SessionRow, SpanRow
from app.db.repositories import SqlReportRepository, SqlSessionRepository
from app.db.seed import DEFAULT_EMPLOYEE_ID, seed_default_users


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await seed_default_users(session)
        yield session

    await engine.dispose()


async def test_list_sessions_reports_turn_count(db_session: AsyncSession) -> None:
    repo = SqlSessionRepository(db_session)
    state = SessionState(session_id="s1", scenario_id="objection_price", current_stage="opening")
    await repo.create(state, user_id=DEFAULT_EMPLOYEE_ID)
    await repo.append_turn(
        "s1", 0, Turn(role=TurnRole.USER, text="Здравствуйте", stage_id="opening", ts=0.0), gen_id=1
    )
    await repo.append_turn(
        "s1", 1, Turn(role=TurnRole.AGENT, text="Добрый день", stage_id="opening", ts=1.0), gen_id=1
    )

    admin = AdminRepository(db_session)
    sessions = await admin.list_sessions()

    assert len(sessions) == 1
    assert sessions[0].session_id == "s1"
    assert sessions[0].turn_count == 2


async def test_list_sessions_reports_stages_completed_from_history(
    db_session: AsyncSession,
) -> None:
    """docs/bugs_front.md №5: номер этапа в админке — честная колонка БД
    (stage_history), не что-то домысленное поверх current_stage."""
    repo = SqlSessionRepository(db_session)
    state = SessionState(
        session_id="s-stages", scenario_id="objection_price", current_stage="objection"
    )
    await repo.create(state, user_id=DEFAULT_EMPLOYEE_ID)

    state.stage_history = [
        StageHistoryEntry(stage_id="opening", turns_spent=3, exit=StageExit.COMPLETE),
        StageHistoryEntry(stage_id="discovery", turns_spent=4, exit=StageExit.COMPLETE),
    ]
    await repo.save_snapshot(state)

    admin = AdminRepository(db_session)
    row = (await admin.list_sessions())[0]

    assert row.stages_completed == 2


async def test_get_session_path_returns_turns_in_order(db_session: AsyncSession) -> None:
    repo = SqlSessionRepository(db_session)
    state = SessionState(session_id="s2", scenario_id="objection_price", current_stage="opening")
    await repo.create(state, user_id=DEFAULT_EMPLOYEE_ID)
    await repo.append_turn(
        "s2", 0, Turn(role=TurnRole.USER, text="первый", stage_id="opening", ts=0.0), gen_id=1
    )
    await repo.append_turn(
        "s2", 1, Turn(role=TurnRole.USER, text="второй", stage_id="discovery", ts=2.0), gen_id=2
    )

    admin = AdminRepository(db_session)
    result = await admin.get_session_path("s2")

    assert result is not None
    summary, turns = result
    assert summary.turn_count == 2
    assert [t.text for t in turns] == ["первый", "второй"]
    assert [t.gen_id for t in turns] == [1, 2]


async def test_mark_finished_sets_status_and_timestamp(db_session: AsyncSession) -> None:
    """Завершение фиксируется сразу, а не на дисконнекте: сотрудник может уйти
    с экрана мгновенно, и тогда save_snapshot уже не спасёт."""
    repo = SqlSessionRepository(db_session)
    state = SessionState(session_id="s-fin", scenario_id="objection_price", current_stage="opening")
    await repo.create(state, user_id=DEFAULT_EMPLOYEE_ID)

    await repo.mark_finished("s-fin")

    admin = AdminRepository(db_session)
    row = (await admin.list_sessions())[0]
    assert row.status == "finished"

    stored = await db_session.get(SessionRow, "s-fin")
    assert stored is not None
    assert stored.finished_at is not None, "колонка finished_at должна наконец писаться"


async def _report(session_id: str, **overrides) -> Report:
    payload = {
        "session_id": session_id,
        "verdict": "Норм",
        "total_score": 3.0,
        "scores": [],
        "transcript": [],
        "duration_sec": 60,
        "stages_completed": 1,
        "stages_total": 1,
    }
    payload.update(overrides)
    return Report.model_validate(payload)


async def test_list_summaries_flags_sessions_with_report(db_session: AsyncSession) -> None:
    """has_report — то, ради чего запрос и писался: без него список сессий
    показывал бы ссылки на несуществующие отчёты."""
    repo = SqlSessionRepository(db_session)
    state = SessionState(session_id="s-rep", scenario_id="objection_price", current_stage="opening")
    await repo.create(state, user_id=DEFAULT_EMPLOYEE_ID)
    await repo.append_turn(
        "s-rep", 0, Turn(role=TurnRole.USER, text="привет", stage_id="opening", ts=0.0), gen_id=1
    )

    assert (await repo.list_summaries())[0].has_report is False

    await SqlReportRepository(db_session).save(await _report("s-rep"))

    summary = (await repo.list_summaries())[0]
    assert summary.has_report is True
    assert summary.turn_count == 1


async def test_list_summaries_hides_empty_sessions(db_session: AsyncSession) -> None:
    """Сессия без единого хода методисту бесполезна — в базе таких большинство,
    потому что раньше строка заводилась на каждый заход на страницу."""
    repo = SqlSessionRepository(db_session)
    await repo.create(
        SessionState(session_id="s-empty", scenario_id="objection_price", current_stage="opening"),
        user_id=DEFAULT_EMPLOYEE_ID,
    )

    assert await repo.list_summaries() == []


async def test_report_save_overwrites(db_session: AsyncSession) -> None:
    """«Пересчитать» обязано работать больше одного раза — на INSERT падало бы
    на дубликате первичного ключа."""
    repo = SqlSessionRepository(db_session)
    await repo.create(
        SessionState(session_id="s-again", scenario_id="objection_price", current_stage="opening"),
        user_id=DEFAULT_EMPLOYEE_ID,
    )
    reports = SqlReportRepository(db_session)

    await reports.save(await _report("s-again", verdict="Первый", total_score=1.0))
    await reports.save(await _report("s-again", verdict="Второй", total_score=4.0))

    stored = await reports.get("s-again")
    assert stored is not None
    assert stored.verdict == "Второй"
    assert stored.total_score == 4.0


async def test_old_report_without_new_fields_still_reads(db_session: AsyncSession) -> None:
    """В базе уже лежат отчёты без scenario_id и model. Обязательные поля
    сделали бы их нечитаемыми — защита дефолтов проверяется здесь."""
    repo = SqlSessionRepository(db_session)
    await repo.create(
        SessionState(session_id="s-old", scenario_id="objection_price", current_stage="opening"),
        user_id=DEFAULT_EMPLOYEE_ID,
    )
    db_session.add(
        ReportRow(
            session_id="s-old",
            verdict="Старый формат",
            total_score=2.0,
            payload={
                "session_id": "s-old",
                "verdict": "Старый формат",
                "total_score": 2.0,
                "scores": [],
                "transcript": [],
                "duration_sec": 30,
                "stages_completed": 1,
                "stages_total": 1,
            },
        )
    )
    await db_session.commit()

    stored = await SqlReportRepository(db_session).get("s-old")
    assert stored is not None
    assert stored.scenario_id == ""
    assert stored.model == ""


async def test_get_session_path_missing_session_returns_none(db_session: AsyncSession) -> None:
    admin = AdminRepository(db_session)
    assert await admin.get_session_path("nope") is None


async def test_list_gens_and_spans(db_session: AsyncSession) -> None:
    repo = SqlSessionRepository(db_session)
    state = SessionState(session_id="s3", scenario_id="objection_price", current_stage="opening")
    await repo.create(state, user_id=DEFAULT_EMPLOYEE_ID)
    await repo.append_turn(
        "s3", 0, Turn(role=TurnRole.USER, text="а сколько стоит?", stage_id="opening", ts=0.0),
        gen_id=1,
    )
    db_session.add(
        SpanRow(
            session_id="s3", gen_id=1, seq=0, operation="character_reply", label="Ирина: ответ",
            start_ms=0, end_ms=500, status="ok", error=None,
        )
    )
    db_session.add(
        SpanRow(
            session_id="s3", gen_id=1, seq=1, operation="tts_synthesize", label="Дорого.",
            start_ms=500, end_ms=900, status="ok", error=None,
        )
    )
    await db_session.commit()

    admin = AdminRepository(db_session)
    gens = await admin.list_gens("s3")
    assert len(gens) == 1
    assert gens[0].gen_id == 1
    assert gens[0].span_count == 2

    spans = await admin.list_spans("s3", 1)
    assert [s.operation for s in spans] == ["character_reply", "tts_synthesize"]
    assert spans[1].start_ms == 500


async def test_list_sessions_reports_user(db_session: AsyncSession) -> None:
    repo = SqlSessionRepository(db_session)
    state = SessionState(session_id="s4", scenario_id="objection_price", current_stage="opening")
    await repo.create(state, user_id=DEFAULT_EMPLOYEE_ID)

    admin = AdminRepository(db_session)
    sessions = await admin.list_sessions()

    assert sessions[0].user_id == DEFAULT_EMPLOYEE_ID
    assert sessions[0].user_display_name == "Сотрудник"

    path = await admin.get_session_path("s4")
    assert path is not None
    assert path[0].user_display_name == "Сотрудник"


async def test_get_load_stats_aggregates_by_operation(db_session: AsyncSession) -> None:
    repo = SqlSessionRepository(db_session)
    state = SessionState(session_id="s5", scenario_id="objection_price", current_stage="opening")
    await repo.create(state, user_id=DEFAULT_EMPLOYEE_ID)

    db_session.add_all(
        [
            SpanRow(
                session_id="s5", gen_id=1, seq=0, operation="character_reply", label="a",
                start_ms=0, end_ms=100, status="ok", error=None,
            ),
            SpanRow(
                session_id="s5", gen_id=1, seq=1, operation="tts_synthesize", label="b",
                start_ms=100, end_ms=300, status="ok", error=None,
            ),
            SpanRow(
                session_id="s5", gen_id=2, seq=0, operation="tts_synthesize", label="c",
                start_ms=0, end_ms=100, status="error", error="boom",
            ),
        ]
    )
    await db_session.commit()

    admin = AdminRepository(db_session)
    stats = await admin.get_load_stats()

    by_op = {o.operation: o for o in stats.operations}
    assert by_op["character_reply"].service == "ai-service"
    assert by_op["tts_synthesize"].service == "speech-service"
    assert by_op["tts_synthesize"].call_count == 2
    assert by_op["tts_synthesize"].error_count == 1
    assert stats.sessions_total == 1
    assert stats.sessions_by_status == {"active": 1}
    assert sum(b.count for b in stats.sessions_timeline) == 1
    assert sum(b.count for b in stats.activity_timeline) == 3


async def test_get_load_stats_buckets_errors_by_service(db_session: AsyncSession) -> None:
    """docs/bugs_front.md №6: ошибки по времени, отдельным списком бакетов на
    каждый сервис — сгруппированы по той же _OPERATION_SERVICE, что и
    OperationLoad.service, без новой агрегации в БД."""
    repo = SqlSessionRepository(db_session)
    await repo.create(
        SessionState(session_id="s-err", scenario_id="objection_price", current_stage="opening"),
        user_id=DEFAULT_EMPLOYEE_ID,
    )
    db_session.add_all(
        [
            SpanRow(
                session_id="s-err", gen_id=1, seq=0, operation="character_reply", label="a",
                start_ms=0, end_ms=100, status="error", error="boom",
            ),
            SpanRow(
                session_id="s-err", gen_id=1, seq=1, operation="tts_synthesize", label="b",
                start_ms=0, end_ms=100, status="error", error="boom",
            ),
            SpanRow(
                session_id="s-err", gen_id=1, seq=2, operation="classify", label="c",
                start_ms=0, end_ms=100, status="ok", error=None,
            ),
        ]
    )
    await db_session.commit()

    stats = await AdminRepository(db_session).get_load_stats()

    assert set(stats.error_timeline) == {"ai-service", "speech-service"}
    assert sum(b.count for b in stats.error_timeline["ai-service"]) == 1
    assert sum(b.count for b in stats.error_timeline["speech-service"]) == 1


async def test_get_load_stats_sums_freed_hours_from_all_reports(db_session: AsyncSession) -> None:
    """Claude.md §11, п.6: счётчик освобождённых часов — агрегат по ВСЕМ
    сессиям, а не одна сессия (баг: та же цифра на /report выглядела как
    «0.02 ч» и дублировала длительность соседней плиткой)."""
    repo = SqlSessionRepository(db_session)
    for session_id in ("s6", "s7"):
        state = SessionState(
            session_id=session_id, scenario_id="objection_price", current_stage="opening"
        )
        await repo.create(state, user_id=DEFAULT_EMPLOYEE_ID)
    reports = SqlReportRepository(db_session)
    await reports.save(await _report("s6", duration_sec=3600))
    await reports.save(await _report("s7", duration_sec=1800))

    stats = await AdminRepository(db_session).get_load_stats()

    assert stats.freed_hours == 1.5
