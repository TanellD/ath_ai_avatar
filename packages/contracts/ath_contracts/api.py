"""Контракты HTTP/WebSocket между сервисами.

Отдельно от §7: это не продуктовые контракты, а внутренние границы сервисов.
Держим их здесь по той же причине — чтобы у gateway и ai-service не завелось
двух разных представлений об одном и том же теле запроса.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter

from ath_contracts.enums import (
    Action,
    Classification,
    Emotion,
    EmotionIntensity,
    OpeningKind,
    SessionStatus,
)
from ath_contracts.report import Report
from ath_contracts.scenario import Persona, RubricItem, Scenario, ScenarioSlot, Stage
from ath_contracts.session import Turn

# --------------------------------------------------------------- ai-service


class CharacterReplyRequest(BaseModel):
    """POST /character/reply → SSE-поток токенов, затем действие."""

    persona: Persona
    stage: Stage
    history: list[Turn] = Field(description="Скользящее окно, уже подготовленное gateway (§5)")
    summary: str = Field(default="", description="Сжатая выжимка вытесненных ходов")
    user_text: str = Field(
        description="Реплика пользователя. Для открывающих реплик (opening_kind != None) "
        "здесь лежит служебная ремарка режиссёра, а не текст человека: Anthropic "
        "Messages API отклоняет пустой список сообщений и список, не начинающийся "
        "с роли user, — см. docs/agent-initiative.md"
    )
    opening_kind: OpeningKind | None = Field(
        default=None,
        description="Заполнено, только когда персонаж говорит сам, без реплики "
        "пользователя: начало сессии или переход на новый этап (§1)",
    )
    off_topic_streak: int = Field(
        default=0,
        description="Сколько реплик подряд классифицированы как off_topic. Влияет "
        "только на тон промпта — автомат этапов об этом не знает (§5)",
    )


class CharacterReplyDone(BaseModel):
    """Последнее SSE-событие потока /character/reply."""

    action: Action = Action.STAY
    full_text: str
    emotion: Emotion = Emotion.NEUTRAL


class CharacterReplyMeta(BaseModel):
    """Первое SSE-событие: управление голосом и лицом до первого предложения."""

    emotion: Emotion


class ClassifyRequest(BaseModel):
    """POST /classify — LLM классифицирует, автомат переходит (§5)."""

    stage: Stage
    history: list[Turn]
    user_text: str


class ClassifyResponse(BaseModel):
    classification: Classification
    reason: str = ""


class EvaluateRequest(BaseModel):
    """POST /evaluate — один вызов сильной модели после завершения (§5)."""

    session_id: str
    scenario: Scenario
    transcript: list[Turn]
    duration_sec: int
    stages_completed: int
    stages_total: int


class EvaluateResponse(BaseModel):
    report: Report


class SummarizeRequest(BaseModel):
    """POST /summarize — сжать вытесненные из окна контекста ходы (§5).

    Инкрементальный вызов: только НОВЫЕ вытесненные ходы + прежняя выжимка,
    а не вся история заново — иначе экономия окна съедается стоимостью
    самой суммаризации (см. gateway/app/orchestrator/context_window.py).
    """

    previous_summary: str = ""
    evicted: list[Turn]


class SummarizeResponse(BaseModel):
    summary: str


# ----------------------------------------------------------- speech-service


class TtsRequest(BaseModel):
    """Кадр запроса в WS /tts/stream.

    Gateway может продолжить запрос кадрами `TtsTextChunk`: первое предложение
    уходит сразу, а `text_end` закрывает всю реплику только после конца LLM.
    """

    gen_id: int
    seq: int
    text: str
    voice_id: str | None = None
    emotion: Emotion = Emotion.NEUTRAL
    intensity: EmotionIntensity = EmotionIntensity.STRONG
    enhanced_prosody: bool = True
    text_end: bool = True


class TtsTextChunk(BaseModel):
    """Следующая часть текста в уже открытом TTS stream."""

    text: str
    text_end: bool = False


class TtsChunk(BaseModel):
    """Кадр ответа WS /tts/stream."""

    gen_id: int
    seq: int
    data: str = Field(description="base64")
    format: str = "wav"
    sample_rate: int = 24000
    is_final: bool = False
    subtitle_text: str = ""
    subtitle_start_ms: int | None = None
    subtitle_end_ms: int | None = None


class SttOpenRequest(BaseModel):
    """Первый JSON-кадр gateway → speech-service перед binary PCM."""

    type: Literal["open"] = "open"
    session_id: str
    capture_id: UUID
    provider_epoch: int = Field(ge=0)
    language: str = "ru"
    context_terms: list[str] = Field(default_factory=list)
    audio_format: Literal["pcm_s16le"] = "pcm_s16le"
    sample_rate: Literal[16000] = 16000
    num_channels: Literal[1] = 1


class SttProgressEvent(BaseModel):
    type: Literal["progress"] = "progress"
    capture_id: UUID
    provider_epoch: int
    provider: str
    audio_samples_processed: int


class SttTranscriptEvent(BaseModel):
    type: Literal["transcript"] = "transcript"
    capture_id: UUID
    provider_epoch: int
    provider: str
    text: str
    confidence: float | None = None


class SttEndpointEvent(BaseModel):
    type: Literal["endpoint"] = "endpoint"
    capture_id: UUID
    provider_epoch: int
    provider: str
    kind: Literal["semantic", "manual", "local_vad"]


class SttFinalEvent(BaseModel):
    type: Literal["final"] = "final"
    capture_id: UUID
    provider_epoch: int
    provider: str
    text: str
    confidence: float | None = None


class SttProviderSwitchedEvent(BaseModel):
    """Внутри одной capture speech-service перешёл на резервный провайдер.

    `partials_available` берётся из capabilities нового движка: gateway не
    должен знать, какие именно провайдеры умеют потоковые партиалы.
    """

    type: Literal["provider_switched"] = "provider_switched"
    capture_id: UUID
    provider_epoch: int
    provider: str
    partials_available: bool


class SttFaultEvent(BaseModel):
    type: Literal["fault"] = "fault"
    capture_id: UUID
    provider_epoch: int
    provider: str
    kind: str
    retryable: bool
    message: str
    provider_request_id: str | None = None


SttServiceEvent = Annotated[
    SttProgressEvent
    | SttTranscriptEvent
    | SttEndpointEvent
    | SttFinalEvent
    | SttProviderSwitchedEvent
    | SttFaultEvent,
    Field(discriminator="type"),
]
_stt_service_adapter: TypeAdapter[SttServiceEvent] = TypeAdapter(SttServiceEvent)


def parse_stt_service_event(data: object) -> SttServiceEvent:
    return _stt_service_adapter.validate_python(data)


# --------------------------------------------------------- scenario-service


class ScenarioSummary(BaseModel):
    """Лёгкое представление для списка сценариев у методиста."""

    id: str
    title: str
    persona_name: str
    stages_count: int
    rubric_count: int
    tags: list[str] = Field(default_factory=list)
    is_template: bool = Field(
        default=False,
        description="Встроенный шаблон: редактор предлагает копировать его, а не править",
    )


class ScenarioListResponse(BaseModel):
    items: list[ScenarioSummary]


# ------------------------------------------------------------------ gateway


class CreateSessionRequest(BaseModel):
    scenario_id: str


class CreateSessionResponse(BaseModel):
    session_id: str
    scenario_id: str
    ws_url: str
    scenario: Scenario = Field(
        description="Сценарий ЭТОГО прогона: детали слотов уже подставлены. "
        "Клиент берёт его отсюда, а не из scenario-service, иначе шапка и "
        "бриф покажут неподставленный текст"
    )


class SessionSummaryItem(BaseModel):
    """Строка списка сессий у методиста (§2: он получает историю и оценку).

    Не путать с админской сводкой из app/db/admin_repository.py: та —
    отладочный инструмент со своей формой (gen_id, спаны), эта — продукт.
    """

    session_id: str
    scenario_id: str
    status: SessionStatus
    turn_count: int
    created_at: str
    finished_at: str | None = None
    has_report: bool = False


class SessionListResponse(BaseModel):
    items: list[SessionSummaryItem]


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str


class ReadyResponse(BaseModel):
    status: str
    dependencies: dict[str, str] = Field(
        default_factory=dict, description="имя зависимости → ok | fail: <причина>"
    )


# ------------------------------------- генерация черновиков методисту (§7)
#
# Сценарий создаётся «из шаблона, из сгенерированного черновика или с нуля».
# Первый и третий пути закрывает CRUD scenario-service, второй — эти ручки.
#
# Ответ здесь всегда ЧЕРНОВИК, а не готовый к сохранению сценарий: он едет в
# форму редактора, методист смотрит и правит. `id` сценария в ответе поэтому
# нет — есть только `suggested_id`, предложение, а не готовое значение: форма
# ставит его в поле «Идентификатор», только пока оно пустое (пустой бланк),
# и никогда не трогает то, что методист уже вписал сам или получил при
# правке/копии существующего сценария.


class ScenarioDraftResponse(BaseModel):
    """Всё, кроме `id`: остальные поля формы редактора.

    `brief` сюда тоже не входит — его написал методист, и переписывать его моделью
    незачем.
    """

    title: str
    suggested_id: str = Field(
        default="",
        description="Латиница, цифры, подчёркивание — годится в адрес страницы "
        "и ключ БД без правки. Форма подставляет его, только если поле "
        "«Идентификатор» ещё пустое",
    )
    """Дефолт пустой не потому, что поле необязательно у настоящего черновика
    (`build_scenario_draft` заполняет его всегда), а потому что этот же тип
    используется и для `ScenarioDraftRequest.current` — снимка того, что уже
    в форме. У формы нет понятия «предложенный id», а плодить под неё
    отдельный тип ради одного поля незачем."""
    persona: Persona
    stages: list[Stage] = Field(min_length=1)
    rubric: list[RubricItem] = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    briefing: str = ""
    slots: list[ScenarioSlot] = Field(default_factory=list)


class ScenarioDraftRequest(BaseModel):
    """POST /scenario/draft — «развернуть черновик» из пары строк."""

    brief: str = Field(min_length=1, description="Что тренируем, своими словами")

    stages_count: int | None = Field(
        default=None,
        ge=1,
        le=8,
        description="Сколько этапов нужно. None — модель решает сама по описанию",
    )
    """`None` — не «сколько-нибудь», а осознанное «реши сам».

    Число этапов — часть методики: разговор либо проходит четыре шага, либо два.
    Методист может его зафиксировать, но по умолчанию решение принимается из описания,
    а не из того, сколько пустых строк оказалось в форме.
    """

    rubric_count: int | None = Field(default=None, ge=1, le=8)

    current: ScenarioDraftResponse | None = Field(
        default=None,
        description="Что методист уже заполнил в форме. Черновик обязан это учесть, "
        "а не спорить с ним",
    )
    """Опора на правку — то, что делает кнопку пригодной не только для пустого бланка.

    Методист правит персонажа руками и просит пересобрать остальное; без этого поля
    модель каждый раз начинала бы с нуля и стирала его формулировки по смыслу, даже
    если в форме они формально сохранились.
    """


class RubricDraftRequest(BaseModel):
    """POST /scenario/rubric — «заполнить критерии» по описанному сценарию."""

    title: str
    persona: Persona
    stages: list[Stage] = Field(min_length=1)
    count: int = Field(default=4, ge=1, le=8)


class RubricDraft(BaseModel):
    """Черновик рубрики — заготовка под генерацию сценария методисту (§7)."""

    items: list[RubricItem]


class ScenarioDetailsRequest(BaseModel):
    """POST /scenario/details — детали под один прогон сценария.

    В отличие от двух ручек выше, эта зовётся не методистом, а gateway при
    создании сессии, и ответ уходит не в форму, а в подстановку по сценарию.
    """

    title: str
    persona_role: str = Field(description="Кем работает персонаж — задаёт правдоподобие деталей")
    briefing: str = Field(description="Скелет с подстановками: показывает, куда попадут значения")
    slots: list[ScenarioSlot] = Field(min_length=1)


class ScenarioDetailsResponse(BaseModel):
    values: dict[str, str] = Field(description="id слота → подобранное значение")
