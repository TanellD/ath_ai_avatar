"""Реестр аватаров: внешность и голос по умолчанию.

Статическая конфигурация, а не данные методиста, поэтому лежит файлом рядом с
шаблонами сценариев и не заводит ни таблицы, ни CRUD. Добавление аватара —
запись в `registry.json`; ни код сервиса, ни фронтенд трогать не нужно.
"""

import json
from functools import lru_cache
from pathlib import Path

from ath_contracts import AvatarProfile

REGISTRY_PATH = Path(__file__).resolve().parent / "registry.json"


class AvatarNotFound(Exception):
    def __init__(self, avatar_id: str) -> None:
        self.avatar_id = avatar_id
        super().__init__(f"аватар {avatar_id!r} не найден в реестре")


@lru_cache
def list_avatars() -> tuple[AvatarProfile, ...]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return tuple(AvatarProfile.model_validate(item) for item in payload["avatars"])


def get_avatar(avatar_id: str) -> AvatarProfile:
    for avatar in list_avatars():
        if avatar.id == avatar_id:
            return avatar
    raise AvatarNotFound(avatar_id)
