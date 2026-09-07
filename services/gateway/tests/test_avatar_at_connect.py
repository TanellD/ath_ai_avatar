"""Голос открывающей реплики — Claude.md §1, §7.

Живой баг с прод-стенда: Vincent произносил ПЕРВУЮ реплику женским голосом и
переключался на свой только со второй. Голос выбирается по avatar_id, а тот
приезжал лишь с user_message — то есть уже после открывающей реплики, которую
персонаж говорит сам. Починено передачей аватара в query-параметре при
открытии сокета (services/gateway/app/api/ws.py).

Здесь закреплено то, ради чего правка делалась: разные аватары обязаны
получать разные голоса, иначе передавать id было бы незачем.
"""

from ath_contracts import Mood, Persona

from app.orchestrator.avatar_voice import DEFAULT_AVATAR_ID, voice_for

PERSONA = Persona(
    name="Ирина",
    role="закупщик",
    character="скептична",
    mood=Mood.NEUTRAL,
    voice_id="Anna",
)


def test_chosen_avatar_overrides_scenario_voice() -> None:
    assert voice_for("vincent-avatar", PERSONA) == "Daniel"


def test_default_avatar_keeps_the_scenario_voice() -> None:
    """Ровно то, что звучало в баге, когда id ещё не доехал до сервера."""
    assert voice_for(DEFAULT_AVATAR_ID, PERSONA) == "Anna"


def test_voices_differ_between_profiles() -> None:
    """Инвариант правки: без разницы в голосах передавать аватар незачем."""
    assert voice_for("vincent-avatar", PERSONA) != voice_for(DEFAULT_AVATAR_ID, PERSONA)
