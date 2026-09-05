"""Run the local GigaAM worker against the private annotated WAV corpus."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
import wave
from pathlib import Path
from typing import Any


def read_manifest(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def read_canonical_wav(path: Path) -> tuple[bytes, float]:
    with wave.open(str(path), "rb") as source:
        if (
            source.getnchannels() != 1
            or source.getsampwidth() != 2
            or source.getframerate() != 16_000
        ):
            raise ValueError(f"{path}: expected PCM16LE mono 16000 Hz WAV")
        frames = source.readframes(source.getnframes())
        return frames, source.getnframes() / source.getframerate()


def transcribe(worker_url: str, pcm: bytes, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{worker_url.rstrip('/')}/transcribe",
        data=pcm,
        method="POST",
        headers={
            "Content-Type": "application/octet-stream",
            "X-Audio-Format": "pcm_s16le",
            "X-Sample-Rate": "16000",
            "X-Audio-Channels": "1",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--worker-url", default="http://localhost:8020")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()

    cases = read_manifest(args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as hypotheses, args.metrics.open(
        "w", encoding="utf-8"
    ) as metrics:
        for index, case in enumerate(cases):
            audio_path = args.manifest.parent / str(case["audio_path"])
            pcm, duration_seconds = read_canonical_wav(audio_path)
            started = time.perf_counter()
            result = transcribe(args.worker_url, pcm, args.timeout)
            request_ms = round((time.perf_counter() - started) * 1000)

            hypotheses.write(
                json.dumps({"id": case["id"], "text": result["text"]}, ensure_ascii=False)
                + "\n"
            )
            inference_ms = int(result["inference_ms"])
            metrics.write(
                json.dumps(
                    {
                        "id": case["id"],
                        "run": "cold" if index == 0 else "warm",
                        "model": result["model"],
                        "audio_seconds": duration_seconds,
                        "request_ms": request_ms,
                        "inference_ms": inference_ms,
                        "rtf": inference_ms / 1000 / duration_seconds,
                        "rss_mb": result.get("rss_mb"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


if __name__ == "__main__":
    main()
