"""Векторное хранилище — ChromaDB, одна коллекция на сценарий.

Один документ на сценарий (issue #11, MVP): повторная загрузка полностью
заменяет предыдущий, а не добавляется к нему — методисту нужен один
актуальный регламент, а не история версий.

`chromadb.PersistentClient` синхронный — каждый вызов уходит в отдельный
поток через `asyncio.to_thread`, чтобы не блокировать event loop FastAPI на
время эмбеддинга/записи на диск.
"""

import asyncio
import contextlib
from datetime import UTC, datetime

import chromadb
from ath_contracts import KnowledgeDocInfo

_META_ID = "__meta__"


class KnowledgeStore:
    def __init__(self, path: str) -> None:
        self._client = chromadb.PersistentClient(path=path)

    def _collection_name(self, scenario_id: str) -> str:
        # ChromaDB требует имя коллекции 3-63 символа, только [a-zA-Z0-9._-].
        # scenario_id у нас и так такой (см. seed/loader.py), но не полагаемся
        # на это молча — режем и подставляем безопасный минимум.
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in scenario_id)
        name = f"kb_{safe}"[:63]
        return name if len(name) >= 3 else name.ljust(3, "_")

    async def replace_document(
        self, scenario_id: str, filename: str, chunks: list[str], embeddings: list[list[float]]
    ) -> KnowledgeDocInfo:
        return await asyncio.to_thread(
            self._replace_document_sync, scenario_id, filename, chunks, embeddings
        )

    def _replace_document_sync(
        self, scenario_id: str, filename: str, chunks: list[str], embeddings: list[list[float]]
    ) -> KnowledgeDocInfo:
        name = self._collection_name(scenario_id)
        # chromadb 1.x кидает NotFoundError, если коллекции ещё не было —
        # это ожидаемый случай (первая загрузка документа), а не ошибка.
        with contextlib.suppress(Exception):
            self._client.delete_collection(name)
        collection = self._client.create_collection(name)

        uploaded_at = datetime.now(UTC).isoformat()
        collection.add(
            ids=[f"chunk-{i}" for i in range(len(chunks))],
            documents=chunks,
            embeddings=embeddings,
            metadatas=[{"filename": filename} for _ in chunks],
        )
        collection.add(
            ids=[_META_ID],
            documents=[""],
            embeddings=[[0.0] * len(embeddings[0])] if embeddings else [[0.0]],
            metadatas=[
                {"filename": filename, "chunk_count": len(chunks), "uploaded_at": uploaded_at}
            ],
        )
        return KnowledgeDocInfo(filename=filename, chunk_count=len(chunks), uploaded_at=uploaded_at)

    async def get_document(self, scenario_id: str) -> KnowledgeDocInfo | None:
        return await asyncio.to_thread(self._get_document_sync, scenario_id)

    def _get_document_sync(self, scenario_id: str) -> KnowledgeDocInfo | None:
        try:
            collection = self._client.get_collection(self._collection_name(scenario_id))
        except Exception:  # noqa: BLE001 — разные версии chromadb кидают разное на "не найдено"
            return None

        result = collection.get(ids=[_META_ID])
        if not result["ids"]:
            return None
        meta = result["metadatas"][0]
        return KnowledgeDocInfo(
            filename=meta["filename"],
            chunk_count=meta["chunk_count"],
            uploaded_at=meta["uploaded_at"],
        )

    async def delete_document(self, scenario_id: str) -> bool:
        return await asyncio.to_thread(self._delete_document_sync, scenario_id)

    def _delete_document_sync(self, scenario_id: str) -> bool:
        name = self._collection_name(scenario_id)
        try:
            self._client.delete_collection(name)
        except Exception:  # noqa: BLE001
            return False
        return True

    async def query(self, scenario_id: str, query_embedding: list[float], top_k: int) -> list[str]:
        return await asyncio.to_thread(self._query_sync, scenario_id, query_embedding, top_k)

    def _query_sync(self, scenario_id: str, query_embedding: list[float], top_k: int) -> list[str]:
        try:
            collection = self._client.get_collection(self._collection_name(scenario_id))
        except Exception:  # noqa: BLE001
            return []

        # +1 и фильтрация __meta__ ниже: он тоже лежит в коллекции (нужен для
        # get_document), но эмбеддинг у него нулевой/бессмысленный и попадать
        # в выдачу не должен.
        result = collection.query(query_embeddings=[query_embedding], n_results=top_k + 1)
        ids = result["ids"][0]
        documents = result["documents"][0]
        return [doc for doc_id, doc in zip(ids, documents, strict=True) if doc_id != _META_ID][
            :top_k
        ]
