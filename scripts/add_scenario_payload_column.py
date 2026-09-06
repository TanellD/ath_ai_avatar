"""Добавить sessions.scenario_payload в существующую БД gateway.

Ревизий alembic в проекте нет, таблицы создаёт `Base.metadata.create_all` при
старте — а он умеет только СОЗДАВАТЬ таблицы и не добавляет колонки в уже
существующие. На чистом клоне (`data/gateway.db` ещё нет) скрипт не нужен
вообще: колонка появится сама. Он нужен там, где база уже наработана и
удалять её вместе с историей сессий незачем.

Тем же способом в этой схеме появилась `scenarios.tags`.

    python scripts/add_scenario_payload_column.py [путь к gateway.db]

Идемпотентен: повторный запуск ничего не делает. Колонка nullable, поэтому
сессии, созданные до неё, продолжают читаться — для них gateway берёт текущую
версию сценария из scenario-service, как было раньше.
"""

import sqlite3
import sys
from pathlib import Path

COLUMN = "scenario_payload"
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "gateway.db"


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB

    if not path.exists():
        print(f"{path} нет — колонка появится сама при первом старте gateway")
        return 0

    with sqlite3.connect(path) as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(sessions)")]
        if not columns:
            print(f"в {path} нет таблицы sessions — база создастся при старте gateway")
            return 0
        if COLUMN in columns:
            print(f"{COLUMN} уже на месте")
            return 0

        db.execute(f"ALTER TABLE sessions ADD COLUMN {COLUMN} JSON")

    print(f"{COLUMN} добавлена в {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
