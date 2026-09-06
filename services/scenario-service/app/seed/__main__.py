"""Обновить встроенные шаблоны из репозитория в уже поднятой базе.

    docker compose exec -T scenario-service python -m app.seed [--force]

Отдельная команда, а не поведение старта, — намеренно. При рестарте шаблоны
не перезаписываются (иначе правки методиста стирались бы сами собой), и из-за
этого правка шаблона в git не доезжает до работающей установки. Так вышло с
`holds_initiative` у interview_junior: в шаблоне `false`, в базе поля нет, и
кандидат на собеседовании продолжал допрашивать интервьюера. Обновление должно
быть решением человека — перед демо, после git pull, — а не побочным эффектом
перезапуска контейнера.
"""

import argparse
import asyncio

from app.db.engine import dispose_engine, init_engine
from app.seed.loader import refresh_templates


async def _run(force: bool) -> int:
    await init_engine()
    try:
        changed = await refresh_templates(force=force)
    finally:
        await dispose_engine()

    if not changed:
        print("шаблоны уже совпадают с репозиторием — нечего обновлять")
    else:
        print(f"обновлено шаблонов: {len(changed)}")
        for scenario_id in changed:
            print(f"  {scenario_id}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="переписать даже совпадающие (если строку правили в обход API)",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.force))


if __name__ == "__main__":
    raise SystemExit(main())
