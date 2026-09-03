"""Засев встроенных шаблонов при старте.

Первый шаг демо — «методист выбирает шаблон, меняет два поля, запускает — за
минуту» (§11). На пустой базе этот шаг сломан, поэтому шаблоны кладутся при
первом запуске.

Существующие сценарии не перезаписываются: методист мог поправить шаблон под
себя, и терять его правку при рестарте контейнера недопустимо.
"""

import json
from pathlib import Path

from ath_contracts import Scenario

from app.core.logging import get_logger
from app.db.engine import session_factory
from app.db.repositories import SqlScenarioRepository

log = get_logger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def load_templates() -> list[Scenario]:
    """Прочитать и провалидировать все шаблоны из каталога.

    Валидация здесь, а не при первом использовании: сломанный шаблон должен
    падать при старте сервиса, а не посреди демо.
    """
    scenarios = []
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        scenarios.append(Scenario.model_validate(data))
    return scenarios


async def seed_templates() -> None:
    templates = load_templates()

    async with session_factory()() as db:
        repository = SqlScenarioRepository(db)
        created = 0
        for scenario in templates:
            if await repository.exists(scenario.id):
                continue
            await repository.upsert(scenario, is_template=True)
            created += 1

    log.info("seed.done", found=len(templates), created=created)
