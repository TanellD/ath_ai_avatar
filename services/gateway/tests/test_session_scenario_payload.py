"""Сценарий прогона: подстановка деталей и её сохранение — Claude.md §7.

Проверяется два инварианта, и оба про то, что тренировка важнее косметики:

  - сбой подбора деталей не имеет права не дать сессии начаться;
  - пересчёт оценки идёт по той рубрике, по которой шёл разговор, а не по
    текущей версии сценария.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from ath_contracts import (
    Mood,
    Persona,
    RubricItem,
    Scenario,
    ScenarioSlot,
    SessionState,
    Stage,
    render_scenario,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.clients.ai_client import AiClient
from app.db.models import Base
from app.db.repositories import SqlSessionRepository
from app.db.seed import DEFAULT_EMPLOYEE_ID, seed_default_users


def scenario_with_slots() -> Scenario:
    return Scenario(
        id="objection_price",
        title="Продажа {product}",
        persona=Persona(
            name="Ирина",
            role="закупщик в «{company}»",
            character="скептична",
            mood=Mood.NEUTRAL,
            difficulty=3,
        ),
        stages=[
            Stage(
                id="opening",
                goal="Выяснить контекст",
                agent_opening="Мы в «{company}» уже всё закупили.",
                completion_criteria="Сотрудник представился",
                max_turns=4,
            )
        ],
        rubric=[
            RubricItem(id="discovery", name="Выявление", description="Спрашивал про {product}")
        ],
        briefing="Вы продаёте {product} компании «{company}».",
        slots=[
            ScenarioSlot(id="company", label="Компания", hint="закупщик", example="Северный Ветер"),
            ScenarioSlot(id="product", label="Продукт", hint="что продаём", example="CRM"),
        ],
    )


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


def ai_client_over(handler: httpx.MockTransport) -> AiClient:
    client = AiClient(base_url="http://ai", timeout=5.0)
    client._client = httpx.AsyncClient(base_url="http://ai", transport=handler)
    return client


async def test_details_failure_falls_back_to_examples_instead_of_raising() -> None:
    """Живой риск: подбор деталей стоит в задержке старта тренировки и ходит в
    ту же модель, что временами не отвечает. Уронить из-за косметической
    детали открытие сессии несоразмерно — сценарий просто останется со
    значениями `example`, и разойтись бриф с персонажем всё равно не сможет.
    """
    scenario = scenario_with_slots()

    def unavailable(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(504, text="gateway timeout")

    values = await ai_client_over(httpx.MockTransport(unavailable)).fill_scenario_details(scenario)

    assert values == {"company": "Северный Ветер", "product": "CRM"}
    rendered = render_scenario(scenario, values)
    assert "{" not in rendered.briefing
    assert rendered.persona.role == "закупщик в «Северный Ветер»"


async def test_scenario_without_slots_never_calls_the_model() -> None:
    """Статичный сценарий незачем гонять через модель — это чистая задержка
    на старте тренировки."""
    calls: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"values": {}})

    static = scenario_with_slots().model_copy(update={"slots": []})

    assert await ai_client_over(httpx.MockTransport(record)).fill_scenario_details(static) == {}
    assert calls == []


async def test_run_scenario_survives_the_methodist_editing_the_original(
    db_session: AsyncSession,
) -> None:
    """Отчёт пересчитывается по ТОЙ рубрике, по которой шёл разговор.

    Раньше `rebuild_report` заново тянул сценарий из scenario-service: правка
    рубрики после тренировки меняла бы оценку задним числом, а удаление
    критерия ломало бы пересчёт совсем.
    """
    repository = SqlSessionRepository(db_session)
    rendered = render_scenario(
        scenario_with_slots(), {"company": "Северный Ветер", "product": "CRM"}
    )
    state = SessionState(
        session_id="s1", scenario_id=rendered.id, current_stage=rendered.stages[0].id
    )

    await repository.create(state, user_id=DEFAULT_EMPLOYEE_ID, scenario=rendered)

    stored = await repository.get_scenario("s1")
    assert stored is not None
    assert stored.briefing == "Вы продаёте CRM компании «Северный Ветер»."
    assert stored.rubric[0].description == "Спрашивал про CRM"


async def test_session_created_before_the_column_reads_as_none(
    db_session: AsyncSession,
) -> None:
    """Колонка nullable, и старые сессии обязаны продолжать открываться: там
    вызывающий берёт текущую версию сценария, как было раньше."""
    repository = SqlSessionRepository(db_session)
    state = SessionState(session_id="old", scenario_id="objection_price", current_stage="opening")

    await repository.create(state, user_id=DEFAULT_EMPLOYEE_ID)

    assert await repository.get_scenario("old") is None
    assert await repository.get_scenario("no-such-session") is None
