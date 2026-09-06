"""Репозиторий сценариев."""

from typing import Protocol

from ath_contracts import Scenario
from ath_contracts.api import ScenarioSummary
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ScenarioRow


class ScenarioRepository(Protocol):
    async def list(self, templates_only: bool = False) -> list[ScenarioSummary]: ...
    async def get(self, scenario_id: str) -> Scenario | None: ...
    async def upsert(self, scenario: Scenario, is_template: bool = False) -> None: ...
    async def delete(self, scenario_id: str) -> bool: ...
    async def exists(self, scenario_id: str) -> bool: ...


class SqlScenarioRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def list(self, templates_only: bool = False) -> list[ScenarioSummary]:
        query = select(ScenarioRow).order_by(ScenarioRow.title)
        if templates_only:
            query = query.where(ScenarioRow.is_template.is_(True))

        rows = (await self._db.scalars(query)).all()
        return [
            ScenarioSummary(
                id=row.id,
                title=row.title,
                persona_name=row.persona_name,
                stages_count=row.stages_count,
                rubric_count=row.rubric_count,
                tags=row.tags,
                is_template=row.is_template,
            )
            for row in rows
        ]

    async def get(self, scenario_id: str) -> Scenario | None:
        row = await self._db.get(ScenarioRow, scenario_id)
        return Scenario.model_validate(row.payload) if row else None

    async def exists(self, scenario_id: str) -> bool:
        return await self._db.get(ScenarioRow, scenario_id) is not None

    async def upsert(self, scenario: Scenario, is_template: bool = False) -> None:
        row = await self._db.get(ScenarioRow, scenario.id)
        payload = scenario.model_dump(mode="json")

        if row is None:
            row = ScenarioRow(id=scenario.id, is_template=is_template)
            self._db.add(row)

        row.title = scenario.title
        row.persona_name = scenario.persona.name
        row.stages_count = len(scenario.stages)
        row.rubric_count = len(scenario.rubric)
        row.tags = scenario.tags
        row.payload = payload

        await self._db.commit()

    async def delete(self, scenario_id: str) -> bool:
        row = await self._db.get(ScenarioRow, scenario_id)
        if row is None:
            return False
        await self._db.delete(row)
        await self._db.commit()
        return True
