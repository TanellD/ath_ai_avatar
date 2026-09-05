import base64
import io
import json
import wave
from pathlib import Path

from ath_contracts.scenario import Persona, RubricItem, Scenario, Stage

from app.orchestrator.avatar_voice import (
    DEFAULT_AVATAR_ID,
    DEFAULT_RECOVERY_LINE,
    known_profiles,
    recovery_line_for,
    voice_for,
)
from app.orchestrator.session_manager import LiveSession
from app.orchestrator.voice_recovery import VoiceRecoveryPlayer, cache_name, write_cache

TOM = "tom-avatar"


def _wav(ms: int) -> str:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16_000)
        handle.writeframes(b"\x00\x00" * (16 * ms))
    return base64.b64encode(buffer.getvalue()).decode()


class FakeSpeech:
    def __init__(self, chunks: list[str] | None = None, *, fail: bool = False) -> None:
        self._chunks = chunks or []
        self._fail = fail
        self.calls: list[dict] = []

    async def stream_tts(self, **kwargs):
        self.calls.append(kwargs)
        if self._fail:
            raise ConnectionError("TTS недоступен")
        for index, data in enumerate(self._chunks):
            yield type("Chunk", (), {"data": data, "seq": index})()


def _session(voice_id: str | None = None) -> LiveSession:
    persona = Persona(name="Ирина", role="закупщик", character="скептична", voice_id=voice_id)
    scenario = Scenario(
        id="s",
        title="t",
        persona=persona,
        stages=[Stage(id="one", goal="g", agent_opening="o", completion_criteria="c")],
        rubric=[RubricItem(id="r", name="Критерий", description="d")],
    )
    return LiveSession(session_id="session", scenario=scenario)


def _player(tmp_path: Path, speech: FakeSpeech, session: LiveSession) -> tuple:
    sent = []

    async def send(event) -> None:  # noqa: ANN001
        sent.append(event)

    return VoiceRecoveryPlayer(
        speech=speech, send=send, session=session, cache_dir=tmp_path
    ), sent


def test_default_line_avoids_gendered_past_tense() -> None:
    # Одна фраза обслуживает персонажей любого рода, поэтому «не расслышал»
    # и «не расслышала» одинаково не годятся.
    assert "расслышал" not in DEFAULT_RECOVERY_LINE
    assert recovery_line_for(DEFAULT_AVATAR_ID) == DEFAULT_RECOVERY_LINE


def test_tom_speaks_in_his_own_voice_and_words() -> None:
    persona = Persona(name="Ирина", role="закупщик", character="скептична", voice_id="Reese")

    assert voice_for(TOM, persona) == "Daniel"
    assert recovery_line_for(TOM) != DEFAULT_RECOVERY_LINE
    # Профиль перекрывает голос персонажа: иначе кот заговорил бы Ириной.
    assert voice_for(DEFAULT_AVATAR_ID, persona) == "Reese"


def test_prerender_covers_every_profile() -> None:
    ids = {avatar_id for avatar_id, _ in known_profiles()}
    assert {DEFAULT_AVATAR_ID, TOM} <= ids


def test_switching_avatar_mid_session_changes_the_recovery_voice(tmp_path: Path) -> None:
    session = _session(voice_id="Reese")
    player, _sent = _player(tmp_path, FakeSpeech(), session)

    before = player._path
    session.avatar_id = TOM
    # Ученик может переключить аватар посреди сессии, и заготовка обязана
    # поехать за ним, а не остаться с голосом предыдущего.
    assert player._path != before


async def test_prerendered_line_plays_without_touching_tts(tmp_path: Path) -> None:
    session = _session(voice_id="Reese")
    write_cache(tmp_path, "Reese", DEFAULT_RECOVERY_LINE, [_wav(500), _wav(300)])
    speech = FakeSpeech(fail=True)
    player, sent = _player(tmp_path, speech, session)

    assert await player.play(gen_id=7) is True
    # Отказ TTS — один из сценариев потери хода, поэтому заготовка обязана
    # звучать, не обращаясь к синтезу.
    assert speech.calls == []
    audio = [event for event in sent if event.type == "audio_chunk"]
    subtitles = [event for event in sent if event.type == "subtitle"]
    assert [event.seq for event in audio] == [0, 1]
    assert all(event.gen_id == 7 for event in audio)
    assert subtitles[0].text == DEFAULT_RECOVERY_LINE
    assert subtitles[0].end_ms == 800


async def test_missing_cache_falls_back_to_live_synthesis(tmp_path: Path) -> None:
    session = _session()
    session.avatar_id = TOM
    speech = FakeSpeech([_wav(200)])
    player, sent = _player(tmp_path, speech, session)

    assert await player.play(gen_id=3) is True
    assert speech.calls[0]["voice_id"] == "Daniel"
    assert [event.type for event in sent] == ["audio_chunk", "subtitle"]


async def test_play_reports_failure_when_nothing_can_be_said(tmp_path: Path) -> None:
    player, sent = _player(tmp_path, FakeSpeech(fail=True), _session())

    # Зовущий обязан узнать, что сказать не удалось, и показать обычную ошибку.
    assert await player.play(gen_id=1) is False
    assert sent == []


async def test_malformed_cache_is_ignored_rather_than_crashing(tmp_path: Path) -> None:
    session = _session(voice_id="Reese")
    path = tmp_path / cache_name("Reese", DEFAULT_RECOVERY_LINE)
    path.write_text(json.dumps({"chunks": "не список"}), encoding="utf-8")
    speech = FakeSpeech([_wav(100)])
    player, sent = _player(tmp_path, speech, session)

    assert await player.play(gen_id=2) is True
    assert len(speech.calls) == 1
    assert len(sent) == 2


def test_cache_key_separates_voices_and_lines() -> None:
    text = DEFAULT_RECOVERY_LINE
    assert cache_name("Reese", text) != cache_name("Daniel", text)
    assert cache_name("Reese", text) != cache_name("Reese", "другая фраза")
    assert cache_name(None, text) == cache_name(None, text)
