"""События WebSocket — Claude.md §7.

Клиент → сервер: в текстовой фазе одно событие вместо трёх аудио-событий.
Сервер → клиент: полный набор из §7 без изменений — ни одно из них не зависит
от того, как пришёл ввод.

**Инвариант (§6): каждое событие сервер → клиент несёт `gen_id`, и клиент
отбрасывает любое событие с `gen_id != current`.** Это то, что держит метрику 4
(возвраты отменённого хвоста = 0) независимо от способа ввода.
"""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter

from ath_contracts.enums import Action, Emotion
from ath_contracts.report import Report

# ---------------------------------------------------------------------------
# Клиент → сервер
# ---------------------------------------------------------------------------


AvatarId = Literal["avatar-aith", "tom-avatar"]
"""Профили аватаров. Рендер-настройки живут на клиенте (AVATAR_MODELS),
сервер знает только, какой голос и какие служебные реплики с ними связаны."""

DEFAULT_AVATAR_ID: AvatarId = "avatar-aith"


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
    avatar_id: AvatarId = Field(
        default=DEFAULT_AVATAR_ID,
        description="Профиль аватара; gateway выбирает связанный с ним голос",
    )


class Ping(BaseModel):
    type: Literal["ping"] = "ping"


class SpeechStart(BaseModel):
    """Открыть одну voice capture; следующие WS binary frames относятся к ней."""

    type: Literal["speech_start"] = "speech_start"
    capture_id: UUID
    interrupts: int | None = None
    # Голос обязан совпадать с текстовым вводом, поэтому профиль приезжает и
    # сюда: у голосового хода своего user_message нет.
    avatar_id: AvatarId = DEFAULT_AVATAR_ID
    mode: Literal["ptt", "hands_free_candidate"] = "ptt"
    audio_format: Literal["pcm_s16le"] = "pcm_s16le"
    sample_rate: Literal[16000] = 16000
    num_channels: Literal[1] = 1


class SpeechEnd(BaseModel):
    """Идемпотентный запрос finalization активной capture."""

    type: Literal["speech_end"] = "speech_end"
    capture_id: UUID


class SpeechAbort(BaseModel):
    """Идемпотентно отменить capture без commit transcript."""

    type: Literal["speech_abort"] = "speech_abort"
    capture_id: UUID


class FinishSession(BaseModel):
    """Сотрудник заканчивает тренировку досрочно.

    Claude.md §3 требует от агента действие «завершить»; автомат делает это
    сам, когда пройден последний этап, но разговор может выдохнуться раньше —
    и тогда без этого события сессия висела бы в active навсегда.
    """

    type: Literal["finish_session"] = "finish_session"


ClientEvent = Annotated[
    UserMessage | SpeechStart | SpeechEnd | SpeechAbort | Ping | FinishSession,
    Field(discriminator="type"),
]

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
    capture_id: UUID
    provider_epoch: int = Field(ge=0)
    provider: str = Field(min_length=1)
    text: str
    is_final: bool
    stt_confidence: float | None = None


class SpeechStartedEvent(BaseModel):
    """Gateway принял capture и связал её с authoritative generation."""

    type: Literal["speech_started"] = "speech_started"
    gen_id: int
    capture_id: UUID


class VoiceProviderSwitchedEvent(BaseModel):
    """[STT] Внутри одной capture распознавание перешло на резервный провайдер.

    Клиенту важно не имя движка, а то, что партиалов больше не будет: замерший
    черновик читается как «меня перестали слышать», хотя запись продолжается.
    UI опирается на `partials_available`, а не на `provider`.
    """

    type: Literal["voice_provider_switched"] = "voice_provider_switched"
    gen_id: int
    capture_id: UUID
    provider_epoch: int = Field(ge=0)
    provider: str = Field(min_length=1)
    partials_available: bool


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
    """Сбой, о котором нужно сообщить клиенту.

    `spoken=True` означает, что персонаж уже объясняет это вслух своим голосом:
    клиент обязан сбросить состояние захвата, но не должен показывать баннер —
    иначе одна и та же неудача сообщается дважды, голосом и красным текстом.
    """

    type: Literal["error"] = "error"
    gen_id: int | None = None
    code: str
    message: str
    spoken: bool = False


ServerEvent = Annotated[
    TokenEvent
    | AudioChunkEvent
    | SubtitleEvent
    | SpeechStartedEvent
    | TranscriptEvent
    | VoiceProviderSwitchedEvent
    | ActionEvent
    | CancelEvent
    | ReportEvent
    | ErrorEvent,
    Field(discriminator="type"),
]
