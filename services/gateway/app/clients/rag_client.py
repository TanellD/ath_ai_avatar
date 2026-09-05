"""Клиент rag-service — база знаний сценария (issue #11).

Простой HTTP JSON, как у scenario-client: querying стоит одного вызова, ничего
не стримится. Ошибки downstream (rag-service не поднят, эмбеддинг упал) не
должны ронять реплику персонажа — RAG для сценария опционален по своей сути
(галочка методиста), поэтому здесь же решение: любая ошибка = пустой
knowledge_context, не исключение наружу. Персонаж отвечает без базы знаний,
а не молчит из-за неё.
"""

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)


class RagClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def ping(self) -> None:
        """Для GET /ready."""
        response = await self._client.get("/health", timeout=3.0)
        response.raise_for_status()

    async def query(self, scenario_id: str, query: str, top_k: int = 3) -> list[str]:
        try:
            response = await self._client.post(
                f"/scenarios/{scenario_id}/knowledge/query",
                json={"query": query, "top_k": top_k},
            )
            response.raise_for_status()
            return response.json()["chunks"]
        except httpx.HTTPError as exc:
            log.warning("rag.query_failed", scenario_id=scenario_id, error=str(exc))
            return []
