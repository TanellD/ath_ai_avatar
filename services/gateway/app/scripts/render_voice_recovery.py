"""Предрендер реплик «повторите, пожалуйста» — по одной на каждый голос.

Запускается до демо (`make voice-recovery-setup`). Собирает все пары
«голос + фраза», которые вообще могут понадобиться: из реестра аватаров и из
персон, которые голос или фразу перекрывают. Синтез идёт тем же TTS, которым
говорит персонаж, поэтому заготовка звучит его голосом.

Новый аватар подхватывается сам: достаточно записи в реестре scenario-service.
"""

import argparse
import asyncio
import sys
from pathlib import Path

import httpx
from ath_contracts import Emotion, Scenario

from app.clients.speech_client import SpeechClient
from app.core.config import get_settings
from app.orchestrator.avatar_voice import known_profiles, voice_for
from app.orchestrator.voice_recovery import write_cache


async def collect(scenario_service_url: str, timeout: float) -> set[tuple[str | None, str]]:
    """Все пары «голос + фраза», которые может потребоваться озвучить.

    Ученик переключает аватар посреди сессии, поэтому нужны все сочетания
    профиля с персоной, а не только исходное.
    """
    profiles = known_profiles()
    wanted: set[tuple[str | None, str]] = set()
    async with httpx.AsyncClient(base_url=scenario_service_url, timeout=timeout) as client:
        listing = await client.get("/scenarios")
        listing.raise_for_status()
        for item in listing.json()["items"]:
            response = await client.get(f"/scenarios/{item['id']}")
            response.raise_for_status()
            persona = Scenario.model_validate(response.json()).persona
            for avatar_id, line in profiles:
                wanted.add((voice_for(avatar_id, persona), line))
    return wanted


async def render(cache_dir: Path, *, scenario_service_url: str, timeout: float) -> int:
    wanted = await collect(scenario_service_url, timeout)
    if not wanted:
        print("сценариев нет — нечего озвучивать", file=sys.stderr)
        return 1

    settings = get_settings()
    speech = SpeechClient(settings.speech_service_url, settings.downstream_timeout_sec)
    failures = 0
    try:
        for voice_id, text in sorted(wanted, key=lambda pair: (pair[0] or "", pair[1])):
            label = voice_id or "голос по умолчанию"
            try:
                chunks = [
                    chunk.data
                    async for chunk in speech.stream_tts(
                        gen_id=0, seq=0, text=text, voice_id=voice_id, emotion=Emotion.NEUTRAL
                    )
                ]
            except Exception as exc:  # noqa: BLE001 - downstream boundary
                print(f"  {label}: синтез не удался: {exc}", file=sys.stderr)
                failures += 1
                continue
            if not chunks:
                print(f"  {label}: TTS вернул пустой результат", file=sys.stderr)
                failures += 1
                continue
            path = write_cache(cache_dir, voice_id, text, chunks)
            print(f"  {label}: {len(chunks)} чанк(ов) -> {path.name}  «{text}»")
    finally:
        await speech.aclose()
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Озвучить реплики восстановления заранее")
    parser.add_argument("--cache-dir", type=Path, default=Path(settings.voice_recovery_dir))
    parser.add_argument("--scenario-service-url", default=settings.scenario_service_url)
    args = parser.parse_args(argv)

    print(f"Реплики восстановления -> {args.cache_dir}")
    return asyncio.run(
        render(
            args.cache_dir,
            scenario_service_url=args.scenario_service_url,
            timeout=settings.downstream_timeout_sec,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
