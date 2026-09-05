import base64
import io
import json
import wave
from pathlib import Path

from ath_contracts import (
    DEFAULT_RECOVERY_LINE,
    AvatarProfile,
    Persona,
    resolve_recovery_line,
    resolve_voice,
)

from app.orchestrator.voice_recovery import VoiceRecoveryPlayer, cache_name, write_cache


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


def _player(
    tmp_path: Path, speech: FakeSpeech, *, voice_id: str | None, text: str = DEFAULT_RECOVERY_LINE
) -> tuple:
    sent = []

    async def send(event) -> None:  # noqa: ANN001
        sent.append(event)

    return VoiceRecoveryPlayer(
        speech=speech, send=send, voice_id=voice_id, text=text, cache_dir=tmp_path
    ), sent


def test_default_line_avoids_gendered_past_tense() -> None:
    # Одна фраза обслуживает персонажей любого рода, поэтому «не расслышал»
    # и «не расслышала» одинаково не годятся.
    assert "расслышал" not in DEFAULT_RECOVERY_LINE
    bare = Persona(name="Ирина", role="закупщик", character="скептична")
    assert resolve_recovery_line(bare, None) == DEFAULT_RECOVERY_LINE


def test_avatar_supplies_voice_and_line_when_persona_is_silent() -> None:
    tom_avatar = AvatarProfile(
        id="tom",
        title="Кот Том",
        model_url="/assets/avatar/tom.glb",
        voice_id="TomVoice",
        recovery_line="Мур? Не расслышал. Повтори-ка.",
    )
    tom = Persona(name="Том", role="кот", character="ленив", avatar_id="tom")

    assert resolve_voice(tom, tom_avatar) == "TomVoice"
    assert resolve_recovery_line(tom, tom_avatar) == "Мур? Не расслышал. Повтори-ка."


def test_persona_overrides_the_avatar() -> None:
    # Одна модель может достаться разным характерам, поэтому персона имеет
    # право звучать иначе, чем аватар по умолчанию.
    avatar = AvatarProfile(id="aith", title="Базовый", model_url="/a.glb", voice_id="Reese")
    pavel = Persona(
        name="Павел",
        role="кандидат",
        character="волнуется",
        voice_id="OtherVoice",
        recovery_line="Извините, повторите?",
    )

    assert resolve_voice(pavel, avatar) == "OtherVoice"
    assert resolve_recovery_line(pavel, avatar) == "Извините, повторите?"


def test_cache_key_separates_voices_and_lines() -> None:
    text = DEFAULT_RECOVERY_LINE
    assert cache_name("Reese", text) != cache_name("TomVoice", text)
    assert cache_name("Reese", text) != cache_name("Reese", "другая фраза")
    assert cache_name(None, text) == cache_name(None, text)


async def test_prerendered_line_plays_without_touching_tts(tmp_path: Path) -> None:
    write_cache(tmp_path, "Reese", DEFAULT_RECOVERY_LINE, [_wav(500), _wav(300)])
    speech = FakeSpeech(fail=True)
    player, sent = _player(tmp_path, speech, voice_id="Reese")

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
    speech = FakeSpeech([_wav(200)])
    player, sent = _player(tmp_path, speech, voice_id="TomVoice")

    assert await player.play(gen_id=3) is True
    assert speech.calls[0]["voice_id"] == "TomVoice"
    assert speech.calls[0]["text"] == DEFAULT_RECOVERY_LINE
    assert [event.type for event in sent] == ["audio_chunk", "subtitle"]


async def test_play_reports_failure_when_nothing_can_be_said(tmp_path: Path) -> None:
    player, sent = _player(tmp_path, FakeSpeech(fail=True), voice_id=None)

    # Зовущий обязан узнать, что сказать не удалось, и показать обычную ошибку.
    assert await player.play(gen_id=1) is False
    assert sent == []


async def test_malformed_cache_is_ignored_rather_than_crashing(tmp_path: Path) -> None:
    path = tmp_path / cache_name("Reese", DEFAULT_RECOVERY_LINE)
    path.write_text(json.dumps({"chunks": "не список"}), encoding="utf-8")
    speech = FakeSpeech([_wav(100)])
    player, sent = _player(tmp_path, speech, voice_id="Reese")

    assert await player.play(gen_id=2) is True
    assert len(speech.calls) == 1
    assert len(sent) == 2
