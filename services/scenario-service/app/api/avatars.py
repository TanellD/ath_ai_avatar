"""Только чтение: аватары — конфигурация проекта, а не данные методиста."""

from ath_contracts import AvatarProfile
from ath_contracts.api import AvatarListResponse
from fastapi import APIRouter, HTTPException, status

from app.avatars import AvatarNotFound, get_avatar, list_avatars
from app.core.logging import get_logger

router = APIRouter(prefix="/avatars", tags=["avatars"])
log = get_logger(__name__)


@router.get("", response_model=AvatarListResponse)
async def list_all() -> AvatarListResponse:
    return AvatarListResponse(items=list(list_avatars()))


@router.get("/{avatar_id}", response_model=AvatarProfile)
async def get_one(avatar_id: str) -> AvatarProfile:
    try:
        return get_avatar(avatar_id)
    except AvatarNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
