"""Засев встроенных шаблонов при старте.

Первый шаг демо — «методист выбирает шаблон, меняет два поля, запускает — за
минуту» (§11). На пустой базе этот шаг сломан, поэтому шаблоны кладутся при
первом запуске.

Существующие сценарии при старте не перезаписываются: методист мог поправить
шаблон под себя, и терять его правку при рестарте контейнера недопустимо.

Обратная сторона — правка шаблона в репозитории не доезжает до уже поднятой
установки. Так и вышло с `holds_initiative` у interview_junior: в шаблоне
`false`, в базе поля нет вовсе, и персонаж-кандидат продолжал допрашивать
интервьюера. Поэтому есть `refresh_templates()` — ОТДЕЛЬНАЯ команда, а не
поведение старта: обновление шаблонов должно быть решением человека, а не
побочным эффектом рестарта.
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


async def refresh_templates(force: bool = False) -> list[str]:
    """Обновить встроенные шаблоны из файлов. Возвращает изменённые id.

    Трогает только строки с `is_template=True`: сценарии, созданные методистом
    с нуля или скопированные из шаблона, — не шаблоны и остаются нетронутыми.
    Модель прямо говорит, что шаблон методист копирует, а не правит
    (`ScenarioRow.is_template`), поэтому обновление встроенного шаблона из
    репозитория — не потеря чужой работы.

    `force` снимает сравнение и переписывает даже совпадающие: нужно, если
    строку правили руками в обход API.
    """
    templates = load_templates()
    changed: list[str] = []

    async with session_factory()() as db:
        repository = SqlScenarioRepository(db)
        for scenario in templates:
            current = await repository.get(scenario.id)
            if current is None:
                # Шаблона в базе нет — это работа seed_templates(), не наша:
                # молча создавать его здесь значило бы дублировать засев.
                continue
            if not force and current == scenario:
                continue
            await repository.upsert(scenario, is_template=True)
            changed.append(scenario.id)

    log.info("seed.refresh_done", found=len(templates), changed=len(changed))
    return changed


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
