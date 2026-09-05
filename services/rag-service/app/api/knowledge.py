"""База знаний сценария — issue #11.

Один документ на сценарий (см. store.py). Методист загружает файл на странице
сценария, gateway дальше дёргает только `/query` — сам файл и эмбеддинги
gateway не касаются.
"""

from ath_contracts import (
    KnowledgeDocInfo,
    KnowledgeListResponse,
    KnowledgeQueryRequest,
    KnowledgeQueryResponse,
    KnowledgeUploadResponse,
)
from fastapi import APIRouter, HTTPException, Request, UploadFile, status

from app.core.config import get_settings
from app.core.logging import get_logger
from app.knowledge.chunking import chunk_text

router = APIRouter(prefix="/scenarios/{scenario_id}/knowledge", tags=["knowledge"])
log = get_logger(__name__)

_ALLOWED_SUFFIXES = (".txt", ".md")


@router.post("", response_model=KnowledgeUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    scenario_id: str, file: UploadFile, request: Request
) -> KnowledgeUploadResponse:
    if not file.filename or not file.filename.lower().endswith(_ALLOWED_SUFFIXES):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"поддерживаются только {', '.join(_ALLOWED_SUFFIXES)}",
        )

    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "файл должен быть в UTF-8") from exc

    settings = get_settings()
    chunks = chunk_text(text, settings.chunk_max_chars, settings.chunk_overlap_chars)
    if not chunks:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "файл пуст")

    embeddings = await request.app.state.embeddings.embed(chunks)
    doc = await request.app.state.store.replace_document(
        scenario_id, file.filename, chunks, embeddings
    )

    log.info(
        "knowledge.uploaded", scenario_id=scenario_id, filename=file.filename, chunks=len(chunks)
    )
    return KnowledgeUploadResponse(doc=doc)


@router.get("", response_model=KnowledgeListResponse)
async def list_documents(scenario_id: str, request: Request) -> KnowledgeListResponse:
    """Список из 0 или 1 документа — контракт множественный, чтобы UI не
    менять, если MVP «один документ» когда-нибудь снимут."""
    doc: KnowledgeDocInfo | None = await request.app.state.store.get_document(scenario_id)
    return KnowledgeListResponse(items=[doc] if doc else [])


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(scenario_id: str, request: Request) -> None:
    await request.app.state.store.delete_document(scenario_id)
    log.info("knowledge.deleted", scenario_id=scenario_id)


@router.post("/query", response_model=KnowledgeQueryResponse)
async def query_document(
    scenario_id: str, payload: KnowledgeQueryRequest, request: Request
) -> KnowledgeQueryResponse:
    """Вызывается gateway'ем перед репликой персонажа и перед оценкой —
    не браузером напрямую (см. Claude.md, разделение ответственности §5)."""
    query_embedding = await request.app.state.embeddings.embed_one(payload.query)
    chunks = await request.app.state.store.query(scenario_id, query_embedding, payload.top_k)
    return KnowledgeQueryResponse(chunks=chunks)
