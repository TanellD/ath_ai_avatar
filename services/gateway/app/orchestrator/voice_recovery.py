"""Реплика персонажа на случай, когда голосовой ход потерян окончательно.

Failover сюда не относится: при переходе на локальный движок аудио
переспрашивается целиком из буфера, ничего не теряется, и извиняться не за что.
Эта реплика звучит только там, где хода действительно нет — оба движка
распознавания отказали, соединение оборвалось или финал пришёл пустым.

Аудио готовится заранее (`make voice-recovery-setup`) по двум причинам. Первая:
отказ TTS — сам по себе один из сценариев, в котором ход теряется, и просить
синтез в этот момент значит просить помощи у того, кто уже упал. Вторая: пауза
на синтез приходится ровно на неловкий момент, когда собеседник ждёт ответа.
"""

import hashlib
import json
from pathlib import Path

from ath_contracts import AudioChunkEvent, Emotion, SubtitleEvent

from app.clients.speech_client import SpeechClient
from app.core.logging import get_logger
from app.orchestrator.avatar_voice import recovery_line_for, voice_for
from app.orchestrator.pipeline import SendFn, wav_duration_ms
from app.orchestrator.session_manager import LiveSession

log = get_logger(__name__)

def cache_name(voice_id: str | None, text: str) -> str:
    """Имя файла заготовки. Голос входит в ключ: одна фраза, много голосов."""
    digest = hashlib.sha256(f"{voice_id or ''}\n{text}".encode()).hexdigest()
    return f"{digest[:16]}.json"


class VoiceRecoveryPlayer:
    """Проигрывает заготовку через тот же путь, что и обычную речь персонажа."""

    def __init__(
        self,
        *,
        speech: SpeechClient,
        send: SendFn,
        session: LiveSession,
        cache_dir: str | Path,
    ) -> None:
        self._speech = speech
        self._send = send
        self._session = session
        self._cache_dir = Path(cache_dir)

    @property
    def _voice_id(self) -> str | None:
        # Читаем на каждом обращении, а не в конструкторе: ученик может
        # переключить аватар посреди сессии, и голос обязан поехать за ним.
        return voice_for(self._session.avatar_id, self._session.scenario.persona)

    @property
    def _text(self) -> str:
        return recovery_line_for(self._session.avatar_id)

    @property
    def _path(self) -> Path:
        return self._cache_dir / cache_name(self._voice_id, self._text)

    async def play(self, gen_id: int) -> bool:
        """Озвучить реплику. False — сказать не удалось, зовущий сам сообщит о сбое."""
        text = self._text
        chunks = self._load()
        if chunks is None:
            # Заготовки нет: пробуем живой синтез, но не притворяемся, что это
            # равноценно — в отказе TTS этот путь тоже не сработает.
            chunks = await self._synthesize(gen_id, text)
        if not chunks:
            return False

        elapsed_ms = 0
        for seq, data in enumerate(chunks):
            await self._send(
                AudioChunkEvent(
                    gen_id=gen_id,
                    seq=seq,
                    data=data,
                    format="wav",
                    emotion=Emotion.NEUTRAL,
                )
            )
            elapsed_ms += wav_duration_ms(data)
        await self._send(
            SubtitleEvent(gen_id=gen_id, text=text, start_ms=0, end_ms=elapsed_ms)
        )
        log.info(
            "voice.recovery_line_spoken",
            gen_id=gen_id,
            voice_id=self._voice_id,
            prerendered=self._path.exists(),
        )
        return True

    def _load(self) -> list[str] | None:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        chunks = payload.get("chunks")
        if not isinstance(chunks, list) or not all(isinstance(item, str) for item in chunks):
            log.warning("voice.recovery_cache_malformed", path=str(self._path))
            return None
        return chunks

    async def _synthesize(self, gen_id: int, text: str) -> list[str]:
        try:
            return [
                chunk.data
                async for chunk in self._speech.stream_tts(
                    gen_id=gen_id,
                    seq=0,
                    text=text,
                    voice_id=self._voice_id,
                    emotion=Emotion.NEUTRAL,
                )
            ]
        except Exception as exc:  # noqa: BLE001 - downstream boundary
            log.warning("voice.recovery_synthesis_failed", error_type=type(exc).__name__)
            return []


def write_cache(cache_dir: Path, voice_id: str | None, text: str, chunks: list[str]) -> Path:
    """Сохранить заготовку. Используется скриптом предрендера."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / cache_name(voice_id, text)
    path.write_text(
        json.dumps(
            {"voice_id": voice_id, "text": text, "format": "wav", "chunks": chunks},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path
