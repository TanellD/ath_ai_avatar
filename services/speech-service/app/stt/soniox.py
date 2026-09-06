"""Soniox realtime STT adapter behind the provider-neutral contract."""

import json
from collections.abc import AsyncIterator

import websockets
from websockets.exceptions import ConnectionClosed

from app.stt.base import (
    EndpointKind,
    EndpointObserved,
    FinalizationComplete,
    NormalizedSttEvent,
    ProviderCapabilities,
    ProviderFault,
    ProviderFaultKind,
    RecognitionProgress,
    SttProvider,
    SttSessionConfig,
    TranscriptHypothesis,
)


class SonioxSttProvider(SttProvider):
    def __init__(self, *, api_key: str, model: str, websocket_url: str) -> None:
        if not api_key:
            raise ValueError("SONIOX_API_KEY is required when STT_PROVIDER=soniox")
        self._api_key = api_key
        self._model = model
        self._websocket_url = websocket_url
        self._config: SttSessionConfig | None = None
        self._ws = None
        self._final_tokens: list[dict[str, object]] = []

    @property
    def name(self) -> str:
        return "soniox"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(True, True, True, True, True, True)

    async def open(self, config: SttSessionConfig) -> None:
        if config.audio_format != "pcm_s16le" or config.sample_rate != 16_000:
            raise ValueError("Soniox STT expects canonical pcm_s16le at 16 kHz")
        if config.num_channels != 1:
            raise ValueError("Soniox STT expects mono audio")

        self._config = config
        self._ws = await websockets.connect(self._websocket_url)
        payload: dict[str, object] = {
            "api_key": self._api_key,
            "model": self._model,
            "audio_format": config.audio_format,
            "sample_rate": config.sample_rate,
            "num_channels": config.num_channels,
            "language_hints": [config.language],
            # PTT owns the endpoint and explicitly sends finalize.
            "enable_endpoint_detection": False,
            "client_reference_id": (
                f"{config.identity.session_id}:{config.identity.capture_id}"
            )[:256],
        }
        if config.context_terms:
            payload["context"] = {"terms": list(config.context_terms)}
        await self._ws.send(json.dumps(payload))

    async def push(self, pcm: bytes) -> None:
        if self._ws is None:
            raise RuntimeError("Soniox STT provider is not open")
        await self._ws.send(pcm)

    async def finalize(self) -> None:
        if self._ws is None:
            raise RuntimeError("Soniox STT provider is not open")
        await self._ws.send(json.dumps({"type": "finalize"}))

    async def events(self) -> AsyncIterator[NormalizedSttEvent]:
        if self._ws is None or self._config is None:
            raise RuntimeError("Soniox STT provider is not open")
        identity = self._config.identity

        try:
            async for raw in self._ws:
                response = json.loads(raw)
                error_code = response.get("error_code")
                if error_code:
                    yield ProviderFault(
                        identity=identity,
                        kind=_fault_kind(str(error_code)),
                        retryable=_is_retryable(str(error_code)),
                        message=str(response.get("error_message") or error_code),
                        provider_request_id=response.get("request_id"),
                    )
                    return

                processed_ms = response.get("total_audio_proc_ms")
                if isinstance(processed_ms, int | float):
                    yield RecognitionProgress(identity, round(processed_ms * 16))

                non_final: list[dict[str, object]] = []
                finalized = False
                for token in response.get("tokens", []):
                    text = str(token.get("text") or "")
                    if text == "<fin>":
                        finalized = True
                    elif text == "<end>":
                        yield EndpointObserved(identity, EndpointKind.SEMANTIC)
                    elif token.get("is_final"):
                        self._final_tokens.append(token)
                    else:
                        non_final.append(token)

                if self._final_tokens or non_final:
                    visible = "".join(
                        str(token.get("text") or "")
                        for token in [*self._final_tokens, *non_final]
                    )
                    yield TranscriptHypothesis(
                        identity=identity,
                        text=visible,
                        is_final=False,
                        confidence=_mean_confidence([*self._final_tokens, *non_final]),
                    )

                if finalized:
                    text = "".join(str(token.get("text") or "") for token in self._final_tokens)
                    yield EndpointObserved(identity, EndpointKind.MANUAL)
                    yield FinalizationComplete(
                        identity=identity,
                        text=text.strip(),
                        confidence=_mean_confidence(self._final_tokens),
                    )
                    return
        except (ConnectionClosed, json.JSONDecodeError) as exc:
            yield ProviderFault(
                identity=identity,
                kind=ProviderFaultKind.DISCONNECTED,
                retryable=True,
                message=str(exc),
            )

    async def aclose(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None


def _mean_confidence(tokens: list[dict[str, object]]) -> float | None:
    values = [float(token["confidence"]) for token in tokens if token.get("confidence") is not None]
    return sum(values) / len(values) if values else None


def _fault_kind(code: str) -> ProviderFaultKind:
    lowered = code.lower()
    if "auth" in lowered:
        return ProviderFaultKind.AUTHENTICATION
    if "rate" in lowered or "limit" in lowered:
        return ProviderFaultKind.RATE_LIMIT
    if "audio" in lowered:
        return ProviderFaultKind.INVALID_AUDIO
    return ProviderFaultKind.INTERNAL


def _is_retryable(code: str) -> bool:
    lowered = code.lower()
    return not any(word in lowered for word in ("auth", "invalid", "audio"))
