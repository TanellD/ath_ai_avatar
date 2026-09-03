"""CRUD сценариев — интерфейс методиста (Claude.md §2, §7).

Сценарий создаётся «из шаблона, из сгенерированного черновика или с нуля».
Первый и третий пути — здесь; генерация черновика пойдёт через ai-service и
появится отдельной ручкой.
"""

from ath_contracts import Scenario
from ath_contracts.api import ScenarioListResponse
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.engine import get_session
from app.db.repositories import SqlScenarioRepository

router = APIRouter(prefix="/scenarios", tags=["scenarios"])
log = get_logger(__name__)


@router.get("", response_model=ScenarioListResponse)
async def list_scenarios(
    templates_only: bool = Query(default=False, description="Только встроенные шаблоны"),
    db: AsyncSession = Depends(get_session),
) -> ScenarioListResponse:
    items = await SqlScenarioRepository(db).list(templates_only=templates_only)
    return ScenarioListResponse(items=items)


@router.get("/{scenario_id}", response_model=Scenario)
async def get_scenario(scenario_id: str, db: AsyncSession = Depends(get_session)) -> Scenario:
    scenario = await SqlScenarioRepository(db).get(scenario_id)
    if scenario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"scenario {scenario_id!r} not found")
    return scenario


@router.put("/{scenario_id}", response_model=Scenario)
async def upsert_scenario(
    scenario_id: str, scenario: Scenario, db: AsyncSession = Depends(get_session)
) -> Scenario:
    """Создать или обновить сценарий.

    PUT, а не POST+PATCH: сценарий всегда сохраняется целиком из редактора
    методиста, частичного обновления полей в этом UI нет.
    """
    if scenario.id != scenario_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"id в пути ({scenario_id!r}) не совпадает с id в теле ({scenario.id!r})",
        )

    await SqlScenarioRepository(db).upsert(scenario)
    log.info("scenario.saved", scenario_id=scenario_id)
    return scenario


@router.post("/{scenario_id}/copy", response_model=Scenario, status_code=status.HTTP_201_CREATED)
async def copy_scenario(
    scenario_id: str,
    new_id: str = Query(description="Идентификатор копии"),
    db: AsyncSession = Depends(get_session),
) -> Scenario:
    """Скопировать сценарий — основной путь «начать с шаблона» (§11).

    Шаблоны не редактируются напрямую: методист копирует и правит копию, иначе
    первый же прогон испортит эталон для всей команды.
    """
    repository = SqlScenarioRepository(db)

    source = await repository.get(scenario_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"scenario {scenario_id!r} not found")

    if await repository.exists(new_id):
        raise HTTPException(status.HTTP_409_CONFLICT, f"scenario {new_id!r} already exists")

    copy = source.model_copy(update={"id": new_id, "title": f"{source.title} (копия)"})
    await repository.upsert(copy)
    log.info("scenario.copied", source=scenario_id, target=new_id)
    return copy


@router.delete("/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scenario(scenario_id: str, db: AsyncSession = Depends(get_session)) -> None:
    if not await SqlScenarioRepository(db).delete(scenario_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"scenario {scenario_id!r} not found")
    log.info("scenario.deleted", scenario_id=scenario_id)
