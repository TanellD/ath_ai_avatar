"""Клиент эмбеддингов — OpenAI-совместимый /v1/embeddings (Ollama).

Отдельный, а не переиспользованный из ai-service клиент: там `LlmProvider`
заточен под chat completions (stream/complete_json), здесь нужен единственный
метод. Дублировать ради общего интерфейса, который не разделяют реальные
сигнатуры, — усложнение без пользы.
"""

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)


class EmbeddingsClient:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        )
        self._model = model

    async def aclose(self) -> None:
        await self._client.aclose()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Эмбеддинги пачкой — один HTTP-вызов на документ, а не на чанк."""
        if not texts:
            return []

        response = await self._client.post(
            "/embeddings", json={"model": self._model, "input": texts}
        )
        response.raise_for_status()
        data = response.json()["data"]
        # API гарантирует порядок ответа = порядку input (OpenAI-контракт).
        return [item["embedding"] for item in data]

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]
