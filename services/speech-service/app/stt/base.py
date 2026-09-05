"""Provider-neutral контракт потокового распознавания.

Dialogue generation остаётся в gateway. Этот слой знает только capture,
provider epoch и нормализованные результаты распознавания.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


@dataclass(frozen=True)
class ProviderCapabilities:
    streaming_partials: bool
    confidence: bool
    token_timestamps: bool
    semantic_endpoint: bool
    context_terms: bool
    manual_finalize: bool


@dataclass(frozen=True)
class RecognitionIdentity:
    session_id: str
    capture_id: UUID
    provider_epoch: int
    provider: str


@dataclass(frozen=True)
class SttSessionConfig:
    identity: RecognitionIdentity
    language: str
    audio_format: str
    sample_rate: int
    num_channels: int
    context_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecognitionProgress:
    identity: RecognitionIdentity
    audio_samples_processed: int


@dataclass(frozen=True)
class TranscriptHypothesis:
    identity: RecognitionIdentity
    text: str
    is_final: bool
    confidence: float | None = None
    start_sample: int | None = None
    end_sample: int | None = None


class EndpointKind(StrEnum):
    SEMANTIC = "semantic"
    MANUAL = "manual"
    LOCAL_VAD = "local_vad"


@dataclass(frozen=True)
class EndpointObserved:
    identity: RecognitionIdentity
    kind: EndpointKind


@dataclass(frozen=True)
class FinalizationComplete:
    identity: RecognitionIdentity
    text: str
    confidence: float | None = None
    start_sample: int | None = None
    end_sample: int | None = None


@dataclass(frozen=True)
class ProviderSwitched:
    """Внутри одной capture управление перешло к другому провайдеру.

    Несёт capabilities нового движка, а не его имя: потребителю важно, что
    дальше не будет партиалов, а не то, какой именно движок их не отдаёт.
    """

    identity: RecognitionIdentity
    capabilities: ProviderCapabilities


class ProviderFaultKind(StrEnum):
    CONNECT = "connect"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    DISCONNECTED = "disconnected"
    STALLED = "stalled"
    INVALID_AUDIO = "invalid_audio"
    INTERNAL = "internal"


@dataclass(frozen=True)
class ProviderFault:
    identity: RecognitionIdentity
    kind: ProviderFaultKind
    retryable: bool
    message: str
    provider_request_id: str | None = None


NormalizedSttEvent = (
    RecognitionProgress
    | TranscriptHypothesis
    | EndpointObserved
    | FinalizationComplete
    | ProviderSwitched
    | ProviderFault
)


class SttProvider(ABC):
    """Одна provider-сессия обслуживает одну capture и один epoch."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    @abstractmethod
    async def open(self, config: SttSessionConfig) -> None: ...

    @abstractmethod
    async def push(self, pcm: bytes) -> None: ...

    @abstractmethod
    async def finalize(self) -> None: ...

    @abstractmethod
    def events(self) -> AsyncIterator[NormalizedSttEvent]: ...

    @abstractmethod
    async def aclose(self) -> None: ...
