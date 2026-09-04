"""События WebSocket — Claude.md §7.

Клиент → сервер: в текстовой фазе одно событие вместо трёх аудио-событий.
Сервер → клиент: полный набор из §7 без изменений — ни одно из них не зависит
от того, как пришёл ввод.

**Инвариант (§6): каждое событие сервер → клиент несёт `gen_id`, и клиент
отбрасывает любое событие с `gen_id != current`.** Это то, что держит метрику 4
(возвраты отменённого хвоста = 0) независимо от способа ввода.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

from ath_contracts.enums import Action, Emotion
from ath_contracts.report import Report

# ---------------------------------------------------------------------------
# Клиент → сервер
# ---------------------------------------------------------------------------


class UserMessage(BaseModel):
    """Реплика пользователя. Отправка = перебивание.

    Заменяет тройку speech_start / user_audio / speech_end из §7. Механизм
    отмены ниже триггера (gen_id → abort → отбрасывание) при этом не меняется
    вообще — меняется только событие, которое его запускает. Клиент к моменту
    отправки УЖЕ локально остановил воспроизведение.
    """

    type: Literal["user_message"] = "user_message"
    text: str = Field(min_length=1)
    interrupts: int | None = Field(
        default=None,
        description="gen_id перебиваемого поколения, либо None если персонаж молчал",
    )
    avatar_id: Literal["avatar-aith", "tom-avatar"] = Field(
        default="avatar-aith",
        description="Профиль аватара; gateway выбирает связанный с ним голос",
    )


class Ping(BaseModel):
    type: Literal["ping"] = "ping"


# --- [STT] Голосовая фаза — объявлено, не подключено. docs/stt-phase.md -----
#
# class SpeechStart(BaseModel):
#     """Onset речи от клиентского VAD. Клиент уже локально остановил звук."""
#     type: Literal["speech_start"] = "speech_start"
#     interrupts: int | None = None
#
# class UserAudio(BaseModel):
#     """Бинарные чанки речи, по порядку."""
#     type: Literal["user_audio"] = "user_audio"
#     seq: int
#     data: bytes
#     format: str
#
# class SpeechEnd(BaseModel):
#     """VAD endpoint. Сигнал STT финализировать транскрипт."""
#     type: Literal["speech_end"] = "speech_end"


ClientEvent = Annotated[UserMessage | Ping, Field(discriminator="type")]

_client_adapter: TypeAdapter[ClientEvent] = TypeAdapter(ClientEvent)


def parse_client_event(raw: dict[str, Any]) -> ClientEvent:
    """Разбор входящего события с валидацией. Кидает pydantic.ValidationError."""
    return _client_adapter.validate_python(raw)


# ---------------------------------------------------------------------------
# Сервер → клиент
# ---------------------------------------------------------------------------


class TokenEvent(BaseModel):
    """Токены реплики персонажа — для субтитров и лога, НЕ для тайминга."""

    type: Literal["token"] = "token"
    gen_id: int
    text: str


class AudioChunkEvent(BaseModel):
    """Чанк аудио, по порядку. Клиент буферизует и воспроизводит.

    Воспроизводимое аудио — единственные часы системы (§3). Ни мимика, ни
    субтитры не имеют права смотреть на что-либо кроме currentTime.
    """

    type: Literal["audio_chunk"] = "audio_chunk"
    gen_id: int
    seq: int
    data: str = Field(description="base64 PCM/WAV")
    format: str = "wav"
    emotion: Emotion = Emotion.NEUTRAL


class SubtitleEvent(BaseModel):
    """Тайминги относительно начала аудио поколения, не абсолютные."""

    type: Literal["subtitle"] = "subtitle"
    gen_id: int
    text: str
    start_ms: int
    end_ms: int


class TranscriptEvent(BaseModel):
    """[STT] Партиалы и финал распознавания реплики пользователя.

    Объявлено, но в текстовой фазе не эмитится никогда: пользователь печатает,
    и его текст возвращается ему же эхом на клиенте.
    """

    type: Literal["transcript"] = "transcript"
    gen_id: int
    text: str
    is_final: bool
    stt_confidence: float | None = None


class ActionEvent(BaseModel):
    type: Literal["action"] = "action"
    gen_id: int
    action: Action
    stage_id: str


class CancelEvent(BaseModel):
    """Поколение отменено. Для клиентов, которые ещё не знают о новом (§6, шаг 5)."""

    type: Literal["cancel"] = "cancel"
    gen_id: int


class ReportEvent(BaseModel):
    """Один раз в конце сессии."""

    type: Literal["report"] = "report"
    gen_id: int
    session_id: str
    report: Report


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    gen_id: int | None = None
    code: str
    message: str


ServerEvent = Annotated[
    TokenEvent
    | AudioChunkEvent
    | SubtitleEvent
    | TranscriptEvent
    | ActionEvent
    | CancelEvent
    | ReportEvent
    | ErrorEvent,
    Field(discriminator="type"),
]
