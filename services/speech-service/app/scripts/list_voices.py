"""Список голосов TTS-провайдера — чтобы выбирать `voice_id` по факту.

Нужен при заведении нового аватара: id голоса подставляется в реестр
scenario-service (`app/avatars/registry.json`).
"""

import argparse
import asyncio
import sys

from app.core.config import get_settings


async def list_soniox_voices(api_key: str, limit: int) -> int:
    from soniox import AsyncSonioxClient

    client = AsyncSonioxClient(api_key=api_key)
    cursor: str | None = None
    shown = 0
    while shown < limit:
        page = await client.voices.list(limit=min(100, limit - shown), cursor=cursor)
        for voice in page.voices:
            print(f"{voice.id:<24} {voice.gender or '-':<8} {voice.description or ''}")
            shown += 1
        cursor = getattr(page, "cursor", None)
        if not cursor:
            break
    if shown == 0:
        print("провайдер не вернул ни одного голоса", file=sys.stderr)
        return 1
    print(f"\nвсего показано: {shown}")
    return 0


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Показать доступные голоса TTS")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args(argv)

    if not settings.soniox_api_key:
        print("SONIOX_API_KEY пуст — список голосов недоступен", file=sys.stderr)
        return 1
    return asyncio.run(list_soniox_voices(settings.soniox_api_key, args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
