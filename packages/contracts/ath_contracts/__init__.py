"""Контракты данных проекта — Claude.md §7.

Единственный источник истины. Сервисы не объявляют свои копии этих моделей:
рассинхрон схем между сервисами — то, на чём разваливается референсный
tatarby-main (`transcriber.ts` и `emotions-parser/app.py` договариваются
о форме JSON исключительно по традиции).

Пакет ставится в каждый сервис через `pip install -e /opt/packages/contracts`,
поэтому контекст сборки Docker — корень репозитория.

TypeScript-зеркало для фронтенда генерируется из JSON Schema:
    python -m ath_contracts.export_schema --out services/frontend/src/contracts/schema.json
"""

from ath_contracts.enums import (
    Action,
    Classification,
    Emotion,
    EmotionIntensity,
    Mood,
    OpeningKind,
    SessionStatus,
    StageExit,
    TurnRole,
)
from ath_contracts.events import (
    DEFAULT_AVATAR_ID,
    AvatarId,
    ActionEvent,
    AudioChunkEvent,
    CancelEvent,
    ClientEvent,
    ErrorEvent,
    FinishSession,
    Ping,
    ReportEvent,
    ServerEvent,
    SilenceTimeout,
    SpeechAbort,
    SpeechEnd,
    SpeechStart,
    SpeechStartedEvent,
    SubtitleEvent,
    TokenEvent,
    TranscriptEvent,
    VoiceProviderSwitchedEvent,
    UserMessage,
    parse_client_event,
)
from ath_contracts.report import AudioRef, CriterionScore, Report
from ath_contracts.scenario import (
    Persona,
    RubricItem,
    Scenario,
    ScenarioSlot,
    Stage,
    render_scenario,
    render_text,
    slot_defaults,
)
from ath_contracts.session import SessionState, StageHistoryEntry, Turn

__all__ = [
    "Action",
    "ActionEvent",
    "AudioChunkEvent",
    "AvatarId",
    "DEFAULT_AVATAR_ID",
    "AudioRef",
    "CancelEvent",
    "Classification",
    "ClientEvent",
    "CriterionScore",
    "Emotion",
    "EmotionIntensity",
    "ErrorEvent",
    "FinishSession",
    "Mood",
    "OpeningKind",
    "Persona",
    "Ping",
    "Report",
    "ReportEvent",
    "RubricItem",
    "Scenario",
    "ScenarioSlot",
    "ServerEvent",
    "SilenceTimeout",
    "SessionState",
    "SessionStatus",
    "Stage",
    "StageExit",
    "StageHistoryEntry",
    "SpeechAbort",
    "SpeechEnd",
    "SpeechStart",
    "SpeechStartedEvent",
    "SubtitleEvent",
    "TokenEvent",
    "TranscriptEvent",
    "VoiceProviderSwitchedEvent",
    "Turn",
    "TurnRole",
    "UserMessage",
    "parse_client_event",
    "render_scenario",
    "render_text",
    "slot_defaults",
]
