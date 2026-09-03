"""Круговой тест AdminRepository: пишем через продуктовые репозитории и
SpanRow напрямую, читаем через админ-чтения. In-memory SQLite, без Docker.
"""

from collections.abc import AsyncIterator

import pytest
from ath_contracts import SessionState, Turn, TurnRole
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.admin_repository import AdminRepository
from app.db.models import Base, SpanRow
from app.db.repositories import SqlSessionRepository
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
