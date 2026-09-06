"""Pinned adapter from canonical PCM16LE to GigaAM 0.2.0.

GigaAM's short-form public API currently accepts a file path.  The worker already
receives normalized 16 kHz mono PCM, so writing a temporary WAV and decoding it
again would add latency and failure modes.  This small compatibility boundary
mirrors ``GigaAMASR.transcribe`` after audio loading and is covered by unit tests.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.setup_models import ModelSetupError, verify_cache


@dataclass(frozen=True)
class Transcription:
    text: str


class GigaAmEngine:
    def __init__(self, *, model_name: str, device: str, cache_dir: str) -> None:
        _require_offline_cache(model_name, cache_dir)

        import gigaam
        import torch

        self._torch = torch
        self._model = gigaam.load_model(
            model_name,
            device=device,
            download_root=cache_dir,
            fp16_encoder=device != "cpu",
            use_flash=False,
        )

    def transcribe_pcm16(self, pcm: bytes) -> Transcription:
        torch = self._torch
        model = self._model

        # bytearray avoids the non-writable-buffer warning from torch.frombuffer.
        wav = torch.frombuffer(bytearray(pcm), dtype=torch.int16).to(torch.float32)
        wav = (wav / 32768.0).to(model._device).to(model._dtype).unsqueeze(0)
        length = torch.full([1], wav.shape[-1], device=model._device)

        with torch.inference_mode():
            encoded, encoded_len = model.forward(wav, length)
            decoded = model.decoding.decode(model.head, encoded, encoded_len)

        text = decoded[0][0] if decoded else ""
        return Transcription(text=str(text).strip())


def _require_offline_cache(model_name: str, cache_dir: str) -> None:
    """The normal start is offline.

    Without this guard ``gigaam.load_model`` would quietly pull the checkpoint
    from the CDN during a demo, and the only symptom would be a stuck ``/ready``.
    """
    try:
        verify_cache(model_name, Path(cache_dir))
    except ModelSetupError as exc:
        raise ModelSetupError(
            f"GigaAM cache is incomplete ({exc}); run `make gigaam-setup` before starting"
        ) from exc


def load_engine(settings: Any) -> GigaAmEngine:
    return GigaAmEngine(
        model_name=settings.gigaam_model,
        device=settings.gigaam_device,
        cache_dir=settings.gigaam_cache_dir,
    )
