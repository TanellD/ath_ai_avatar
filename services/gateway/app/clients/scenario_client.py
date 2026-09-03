"""Клиент scenario-service. Простой HTTP JSON — стримить здесь нечего."""

import httpx
from ath_contracts import Scenario

from app.core.logging import get_logger

log = get_logger(__name__)


class ScenarioNotFound(Exception):
    def __init__(self, scenario_id: str) -> None:
        super().__init__(f"scenario {scenario_id!r} not found")
        self.scenario_id = scenario_id


class ScenarioClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def ping(self) -> None:
        """Для GET /ready."""
        response = await self._client.get("/health", timeout=3.0)
        response.raise_for_status()

    async def get(self, scenario_id: str) -> Scenario:
        """Сценарий целиком. Кэша нет намеренно: методист правит сценарий между
        прогонами, и подхватывать правку на старте сессии — правильное
        поведение."""
        response = await self._client.get(f"/scenarios/{scenario_id}")
        if response.status_code == 404:
            raise ScenarioNotFound(scenario_id)
        response.raise_for_status()
        return Scenario.model_validate(response.json())
