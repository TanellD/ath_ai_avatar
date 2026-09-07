"""Голос открывающей реплики — Claude.md §1, §7.

Живой баг с прод-стенда: Vincent произносил ПЕРВУЮ реплику женским голосом и
переключался на свой только со второй. Голос выбирается по avatar_id, а тот
приезжал лишь с user_message — то есть уже после открывающей реплики, которую
персонаж говорит сам. Починено передачей аватара в query-параметре при
открытии сокета (services/gateway/app/api/ws.py), который кладёт его в
LiveSession.avatar_id ДО open_session().

Этого оказалось недостаточно: два фикса подряд (505a8fc, ac51a9c) чинили
только транспорт и ни разу не трогали pipeline.py — `_run_opening` продолжал
жёстко подставлять DEFAULT_AVATAR_ID вместо чтения self._session.avatar_id, и
баг пережил оба «фикса» невидимо для тестов, проверявших только чистую
функцию voice_for(). test_opening_uses_the_session_avatar ниже прогоняет
реальный путь session.avatar_id -> open_session() -> TTS, а не только резолвер.
"""

import pytest
from ath_contracts import Mood, Persona, Scenario

from app.orchestrator.avatar_voice import DEFAULT_AVATAR_ID, voice_for
from app.orchestrator.session_manager import LiveSession
from tests.conftest import build_pipeline, drain

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


async def test_opening_uses_the_session_avatar(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Регрессия: ws.py выставляет session.avatar_id ДО open_session() именно
    затем, чтобы открывающая реплика звучала выбранным голосом. Здесь это
    проверяется сквозь весь путь, а не только через voice_for() — старый баг
    жил в _run_opening, который игнорировал session.avatar_id и не был виден
    ни одному из тестов выше.
    """
    session = LiveSession(session_id="s-vincent", scenario=scenario)
    session.avatar_id = "vincent-avatar"
    pipeline, _ai, speech, _sent = build_pipeline(session, monkeypatch)

    await pipeline.open_session()
    await drain(session)

    assert speech.voices, "открывающая реплика должна была дойти до TTS"
    assert speech.voices[0] == "Daniel", (
        "первая реплика Vincent прозвучала не его голосом — "
        f"got {speech.voices[0]!r}"
    )
