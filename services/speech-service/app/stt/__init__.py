"""Provider-neutral primitives будущего STT pipeline."""

from app.stt.base import (
    EndpointKind,
    EndpointObserved,
    FinalizationComplete,
    NormalizedSttEvent,
    ProviderCapabilities,
    ProviderFault,
    ProviderFaultKind,
    ProviderSwitched,
    RecognitionIdentity,
    RecognitionProgress,
    SttProvider,
    SttSessionConfig,
    TranscriptHypothesis,
)
from app.stt.capture_buffer import CaptureBuffer
from app.stt.mock import MockSttProvider

__all__ = [
    "CaptureBuffer",
    "EndpointKind",
    "EndpointObserved",
    "FinalizationComplete",
    "MockSttProvider",
    "NormalizedSttEvent",
    "ProviderCapabilities",
    "ProviderFault",
    "ProviderFaultKind",
    "ProviderSwitched",
    "RecognitionIdentity",
    "RecognitionProgress",
    "SttProvider",
    "SttSessionConfig",
    "TranscriptHypothesis",
]
