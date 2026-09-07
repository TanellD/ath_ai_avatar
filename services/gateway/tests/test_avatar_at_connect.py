"""Аватар, сообщённый при подключении, — Claude.md §7.

Живой баг: Vincent произносил ПЕРВУЮ реплику женским голосом и переключался на
свой только со второй. Голос выбирается по avatar_id, а тот приезжал лишь с
user_message — то есть уже после открывающей реплики, которую персонаж говорит
сам (§1). Теперь id приходит параметром подключения, до открытия разговора.
"""

import pytest
from ath_contracts import Mood, Persona

from app.orchestrator.avatar_voice import DEFAULT_AVATAR_ID, resolve_avatar_id, voice_for

PERSONA = Persona(
    name="Ирина",
    role="закупщик",
    character="скептична",
    mood=Mood.NEUTRAL,
    voice_id="Anna",
)


def test_known_avatar_is_accepted() -> None:
    assert resolve_avatar_id("vincent-avatar", DEFAULT_AVATAR_ID) == "vincent-avatar"


@pytest.mark.parametrize("requested", [None, "", "avatar-of-nobody"])
def test_unknown_avatar_keeps_the_current_one(requested: str | None) -> None:
    """Опечатка в адресной строке не должна подменять выбранного персонажа."""
    assert resolve_avatar_id(requested, "vincent-avatar") == "vincent-avatar"


def test_opening_line_gets_the_right_voice() -> None:
    """Смысл всей правки: голос считается по тому же id и до первой реплики.

    Без разрешения на подключении здесь стоял бы DEFAULT_AVATAR_ID, и
    `voice_for` вернул бы голос персонажа сценария — женский «Anna».
    """
    avatar_id = resolve_avatar_id("vincent-avatar", DEFAULT_AVATAR_ID)

    assert voice_for(avatar_id, PERSONA) == "Daniel"
    assert voice_for(DEFAULT_AVATAR_ID, PERSONA) == "Anna"
