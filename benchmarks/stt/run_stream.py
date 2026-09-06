"""Прогон корпуса через рабочий `/stt/stream` speech-service.

`run_gigaam.py` бьёт в worker напрямую по HTTP и меряет только пакетный
инференс. Здесь идёт тот же путь, что и в проде: WebSocket, канонический PCM
кадрами, нормализованные события. Только так измеряются `first_partial` и
`finalization` из §K плана — у HTTP-раннера партиалов нет в принципе.

Провайдер выбирается конфигом speech-service (`STT_PROVIDER`), поэтому один и
тот же раннер снимает метрики и с Soniox, и с GigaAM, и с их связки.

    python benchmarks/stt/run_stream.py \
      --manifest benchmarks/stt/manifest.local.jsonl \
      --output   benchmarks/stt/results/soniox.jsonl \
      --metrics  benchmarks/stt/results/soniox.metrics.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import wave
from pathlib import Path
from typing import Any
from uuid import uuid4

import websockets

SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2


def read_manifest(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def read_canonical_wav(path: Path) -> tuple[bytes, float]:
    with wave.open(str(path), "rb") as source:
        if (
            source.getnchannels() != 1
            or source.getsampwidth() != BYTES_PER_SAMPLE
            or source.getframerate() != SAMPLE_RATE
        ):
            raise ValueError(f"{path}: expected PCM16LE mono 16000 Hz WAV")
        frames = source.readframes(source.getnframes())
        return frames, source.getnframes() / source.getframerate()


def frames(pcm: bytes, chunk_ms: int) -> list[bytes]:
    """Нарезка на кадры фиксированной длительности, как это делает браузер."""
    step = int(SAMPLE_RATE * chunk_ms / 1000) * BYTES_PER_SAMPLE
    if step <= 0:
        raise ValueError("chunk_ms слишком мал")
    return [pcm[offset : offset + step] for offset in range(0, len(pcm), step)]


class CaseResult:
    """Собирает метрики одного прогона. Времена — от начала отправки аудио."""

    def __init__(self, case_id: str, audio_seconds: float) -> None:
        self.case_id = case_id
        self.audio_seconds = audio_seconds
        self.text = ""
        self.provider = ""
        self.provider_epoch = 0
        self.partials = 0
        self.switched = False
        self.first_partial_ms: int | None = None
        self.finalization_ms: int | None = None
        self.final_at: float | None = None
        self.error: str | None = None

    def as_hypothesis(self) -> dict[str, Any]:
        return {"id": self.case_id, "text": self.text}

    def as_metrics(self, run: str) -> dict[str, Any]:
        return {
            "id": self.case_id,
            "run": run,
            "provider": self.provider,
            "provider_epoch": self.provider_epoch,
            "audio_seconds": round(self.audio_seconds, 3),
            "first_partial_ms": self.first_partial_ms,
            "finalization_ms": self.finalization_ms,
            "partials": self.partials,
            "switched": self.switched,
            "error": self.error,
        }


async def run_case(
    url: str, case_id: str, pcm: bytes, audio_seconds: float, *, chunk_ms: int, realtime: bool
) -> CaseResult:
    result = CaseResult(case_id, audio_seconds)
    capture_id = str(uuid4())

    async with websockets.connect(url) as socket:
        await socket.send(
            json.dumps(
                {
                    "type": "open",
                    "session_id": f"bench-{capture_id}",
                    "capture_id": capture_id,
                    "provider_epoch": 0,
                    "language": "ru",
                    "audio_format": "pcm_s16le",
                    "sample_rate": SAMPLE_RATE,
                    "num_channels": 1,
                }
            )
        )

        started = time.perf_counter()
        collector = asyncio.create_task(_collect(socket, result, started))

        for frame in frames(pcm, chunk_ms):
            await socket.send(frame)
            if realtime:
                # Без выдержки темпа партиалы приходят на уже полностью
                # отправленном аудио, и first_partial перестаёт что-либо значить.
                await asyncio.sleep(chunk_ms / 1000)

        finalize_sent = time.perf_counter()
        await socket.send(json.dumps({"type": "finalize"}))
        await collector

    if result.final_at is not None:
        # §K: finalization = final_visible - speech_end, то есть от запроса
        # финализации, а не от начала записи.
        result.finalization_ms = round((result.final_at - finalize_sent) * 1000)
    elif result.error is None:
        result.error = "final не пришёл"
    return result


async def _collect(socket: Any, result: CaseResult, started: float) -> None:
    try:
        async for raw in socket:
            event = json.loads(raw)
            kind = event.get("type")
            if kind == "transcript":
                result.partials += 1
                if result.first_partial_ms is None:
                    result.first_partial_ms = round((time.perf_counter() - started) * 1000)
            elif kind == "provider_switched":
                result.switched = True
            elif kind == "final":
                result.text = event.get("text", "")
                result.provider = event.get("provider", "")
                result.provider_epoch = int(event.get("provider_epoch", 0))
                result.final_at = time.perf_counter()
                return
            elif kind == "fault":
                result.error = f"{event.get('kind')}: {event.get('message')}"
                return
    except Exception as exc:  # noqa: BLE001 - раннер, а не сервис
        result.error = f"{type(exc).__name__}: {exc}"


async def main_async(args: argparse.Namespace) -> None:
    cases = read_manifest(args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.metrics.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("w", encoding="utf-8") as hypotheses, args.metrics.open(
        "w", encoding="utf-8"
    ) as metrics:
        for index, case in enumerate(cases):
            audio_path = args.manifest.parent / str(case["audio_path"])
            pcm, audio_seconds = read_canonical_wav(audio_path)
            result = await run_case(
                args.url,
                str(case["id"]),
                pcm,
                audio_seconds,
                chunk_ms=args.chunk_ms,
                realtime=not args.as_fast_as_possible,
            )
            hypotheses.write(json.dumps(result.as_hypothesis(), ensure_ascii=False) + "\n")
            metrics.write(
                json.dumps(
                    result.as_metrics("cold" if index == 0 else "warm"), ensure_ascii=False
                )
                + "\n"
            )
            note = result.error or f"{result.partials} партиал(ов)"
            print(f"  {case['id']}: {note}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--url", default="ws://localhost:8010/stt/stream")
    parser.add_argument("--chunk-ms", type=int, default=20)
    parser.add_argument(
        "--as-fast-as-possible",
        action="store_true",
        help="слать аудио без выдержки темпа; first_partial станет бессмысленным",
    )
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
