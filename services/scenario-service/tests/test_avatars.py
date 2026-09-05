"""Реестр аватаров и его согласованность с шаблонами сценариев."""

import json
from pathlib import Path

import pytest
from ath_contracts import DEFAULT_AVATAR_ID

from app.avatars import AvatarNotFound, get_avatar, list_avatars
from app.avatars.registry import REGISTRY_PATH

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "app" / "seed" / "templates"


def test_registry_parses_and_ids_are_unique() -> None:
    avatars = list_avatars()
    ids = [avatar.id for avatar in avatars]

    assert avatars, "реестр не должен быть пустым"
    assert len(ids) == len(set(ids)), f"дубли id в реестре: {ids}"


def test_default_avatar_exists() -> None:
    # Персона без явного avatar_id получает именно этот id, поэтому его
    # отсутствие сломало бы любой сценарий, где аватар не указан.
    assert get_avatar(DEFAULT_AVATAR_ID).model_url


def test_unknown_avatar_is_reported() -> None:
    with pytest.raises(AvatarNotFound):
        get_avatar("нет такого")


def test_every_seeded_persona_points_at_a_known_avatar() -> None:
    known = {avatar.id for avatar in list_avatars()}

    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        persona = json.loads(path.read_text(encoding="utf-8"))["persona"]
        avatar_id = persona.get("avatar_id", DEFAULT_AVATAR_ID)
        assert avatar_id in known, f"{path.name}: аватар {avatar_id!r} отсутствует в реестре"


def test_model_urls_are_absolute_frontend_paths() -> None:
    # Путь отдаётся браузеру как есть; относительный сломался бы на вложенных
    # маршрутах вроде /session/<id>.
    for avatar in list_avatars():
        assert avatar.model_url.startswith("/"), avatar.id


def test_registry_file_has_no_trailing_placeholders() -> None:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    for item in payload["avatars"]:
        assert item["model_url"] and not item["model_url"].endswith("/"), item["id"]
