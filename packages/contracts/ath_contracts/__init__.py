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
    Mood,
    SessionStatus,
    StageExit,
    TurnRole,
)
from ath_contracts.events import (
    ActionEvent,
    AudioChunkEvent,
    CancelEvent,
    ClientEvent,
    ErrorEvent,
    Ping,
    ReportEvent,
    ServerEvent,
    SubtitleEvent,
    TokenEvent,
    TranscriptEvent,
    UserMessage,
    parse_client_event,
)
from ath_contracts.report import AudioRef, CriterionScore, Report
from ath_contracts.scenario import Persona, RubricItem, Scenario, Stage
from ath_contracts.session import SessionState, StageHistoryEntry, Turn

__all__ = [
    "Action",
    "ActionEvent",
    "AudioChunkEvent",
    "AudioRef",
    "CancelEvent",
    "Classification",
    "ClientEvent",
    "CriterionScore",
    "ErrorEvent",
    "Mood",
    "Persona",
    "Ping",
    "Report",
    "ReportEvent",
    "RubricItem",
    "Scenario",
    "ServerEvent",
    "SessionState",
    "SessionStatus",
    "Stage",
    "StageExit",
    "StageHistoryEntry",
    "SubtitleEvent",
    "TokenEvent",
    "TranscriptEvent",
    "Turn",
    "TurnRole",
    "UserMessage",
    "parse_client_event",
]
