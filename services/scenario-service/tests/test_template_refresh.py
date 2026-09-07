"""Обновление встроенных шаблонов из репозитория.

Живой случай, ради которого команда и написана: в шаблоне interview_junior
стоит `holds_initiative: false`, а в поднятой базе поля не было вовсе —
строка записана до этой правки, а засев существующие сценарии пропускает.
Персонаж-кандидат из-за этого продолжал допрашивать интервьюера, хотя фикс
лежал в репозитории.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from ath_contracts import Scenario

from app.db import engine as engine_module
from app.db.repositories import SqlScenarioRepository
from app.seed.loader import load_templates, refresh_templates, seed_templates


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'scenarios.db'}")
    engine_module.get_settings.cache_clear()
    await engine_module.init_engine()
    yield
    await engine_module.dispose_engine()
    engine_module.get_settings.cache_clear()


def _template(scenario_id: str) -> Scenario:
    for scenario in load_templates():
        if scenario.id == scenario_id:
            return scenario
    pytest.fail(f"шаблона {scenario_id} нет в каталоге")


async def test_refresh_updates_stale_template(db: None) -> None:
    """Строка, отставшая от репозитория, догоняет его."""
    template = _template("interview_junior")
    stale = template.model_copy(deep=True)
    stale.persona.holds_initiative = not template.persona.holds_initiative

    async with engine_module.session_factory()() as session:
        await SqlScenarioRepository(session).upsert(stale, is_template=True)

    assert await refresh_templates() == ["interview_junior"]

    async with engine_module.session_factory()() as session:
        current = await SqlScenarioRepository(session).get("interview_junior")
    assert current is not None
    assert current.persona.holds_initiative == template.persona.holds_initiative


async def test_refresh_leaves_methodist_scenarios_alone(db: None) -> None:
    """Сценарий методиста — не шаблон, и обновление его не касается.

    Это условие, при котором командой вообще можно пользоваться: если бы она
    перезаписывала чужую работу, безопасного момента для запуска не было бы.
    """
    template = _template("interview_junior")
    mine = template.model_copy(deep=True)
    mine.id = "my_own_interview"
    mine.title = "Моя правка"

    async with engine_module.session_factory()() as session:
        await SqlScenarioRepository(session).upsert(mine, is_template=False)

    await refresh_templates(force=True)

    async with engine_module.session_factory()() as session:
        current = await SqlScenarioRepository(session).get("my_own_interview")
    assert current is not None
    assert current.title == "Моя правка"


async def test_refresh_is_idempotent_and_does_not_create(db: None) -> None:
    """На совпадающих шаблонах — ноль изменений; отсутствующие не создаёт.

    Создание — работа `seed_templates()`; дублировать её здесь значило бы
    завести второй путь засева, который разъедется с первым.
    """
    assert await refresh_templates() == [], "на пустой базе обновлять нечего"

    await seed_templates()
    assert await refresh_templates() == []
