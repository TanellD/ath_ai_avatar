"""Контракты HTTP между сервисами.

Отдельно от §7: это не продуктовые контракты, а внутренние границы сервисов.
Держим их здесь по той же причине — чтобы у gateway и ai-service не завелось
двух разных представлений об одном и том же теле запроса.
"""

from pydantic import BaseModel, Field

from ath_contracts.enums import (
    Action,
    Classification,
    Emotion,
    EmotionIntensity,
    OpeningKind,
    SessionStatus,
)
from ath_contracts.report import Report
from ath_contracts.scenario import Persona, RubricItem, Scenario, Stage
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


# ----------------------------------------------------------- speech-service


class TtsRequest(BaseModel):
    """Кадр запроса в WS /tts/stream.

    Дробление по предложениям делает gateway: первое предложение уходит сюда
    сразу, не дожидаясь конца генерации LLM (§10).
    """

    gen_id: int
    seq: int
    text: str
    voice_id: str | None = None
    emotion: Emotion = Emotion.NEUTRAL
    intensity: EmotionIntensity = EmotionIntensity.STRONG
    enhanced_prosody: bool = True


class TtsChunk(BaseModel):
    """Кадр ответа WS /tts/stream."""

    gen_id: int
    seq: int
    data: str = Field(description="base64")
    format: str = "wav"
    sample_rate: int = 24000
    is_final: bool = False


# --------------------------------------------------------- scenario-service


class ScenarioSummary(BaseModel):
    """Лёгкое представление для списка сценариев у методиста."""

    id: str
    title: str
    persona_name: str
    stages_count: int
    rubric_count: int


class ScenarioListResponse(BaseModel):
    items: list[ScenarioSummary]


# ------------------------------------------------------------------ gateway


class CreateSessionRequest(BaseModel):
    scenario_id: str


class CreateSessionResponse(BaseModel):
    session_id: str
    scenario_id: str
    ws_url: str


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


class RubricDraft(BaseModel):
    """Черновик рубрики — заготовка под генерацию сценария методисту (§7)."""

    items: list[RubricItem]
