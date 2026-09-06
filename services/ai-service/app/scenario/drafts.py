"""Сборка черновиков из сырого ответа модели.

Тот же принцип, что в `evaluation/report_builder.py`: схема — не гарантия.
`output_config.format` держит форму на настоящем api.anthropic.com, но
`AnthropicProvider` умеет ходить через сторонний шлюз (§10), а шлюз не обязан
поддерживать её так же полно; `openai_compatible` и вовсе просит JSON текстом.
Поэтому всё, что схема лишь описывает, здесь проверяется кодом.

Чинится ровно два класса ответов, и оба — реальные ловушки:

- **id не годится в идентификатор.** Модель охотно вернёт «Работа с
  возражением» или «objection-handling». Такой id уходит в форму, методист
  сохраняет — и получает либо отказ валидации (`^[a-z0-9_-]{1,128}$` в
  scenario/validate.ts), либо кириллицу в адресе страницы. Приводим к слагу
  здесь, а не показываем методисту ошибку в поле, которое заполнил не он.

- **id повторяются.** Схема этого не запрещает, а последствия молчаливые:
  дубликат `stage.id` схлопывает словарь `StageMachine` и ломает переходы по
  этапам, дубликат `rubric[].id` отбраковывает отчёт уже после пройденной
  сессии. Разводим суффиксом.
"""

import re

from ath_contracts import Persona, RubricItem, Stage
from ath_contracts.api import RubricDraft, ScenarioDraftResponse

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(raw: str, fallback: str) -> str:
    """Идентификатор становится сегментом URL и ключом в БД, а не подписью."""
    slug = _NON_SLUG.sub("_", raw.strip().lower()).strip("_")
    return slug[:128] if slug else fallback


def _unique_ids(raw_items: list[dict], prefix: str) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()

    for index, item in enumerate(raw_items, start=1):
        candidate = _slug(str(item.get("id", "")), f"{prefix}_{index}")
        # Суффикс, а не отбрасывание: у второго этапа с тем же именем своё
        # содержание, и терять его из-за неудачного идентификатора незачем.
        unique, attempt = candidate, 2
        while unique in seen:
            unique = f"{candidate}_{attempt}"
            attempt += 1

        seen.add(unique)
        ids.append(unique)

    return ids


def _rubric_items(raw_items: list[dict]) -> list[RubricItem]:
    ids = _unique_ids(raw_items, "criterion")
    return [
        RubricItem.model_validate({**item, "id": item_id})
        for item, item_id in zip(raw_items, ids, strict=True)
    ]


def build_rubric_draft(raw: dict) -> RubricDraft:
    return RubricDraft(items=_rubric_items(raw.get("items", [])))


def build_scenario_draft(raw: dict) -> ScenarioDraftResponse:
    raw_stages = raw.get("stages", [])
    stage_ids = _unique_ids(raw_stages, "stage")

    return ScenarioDraftResponse(
        title=raw.get("title", ""),
        persona=Persona.model_validate(raw.get("persona", {})),
        stages=[
            Stage.model_validate({**stage, "id": stage_id})
            for stage, stage_id in zip(raw_stages, stage_ids, strict=True)
        ],
        rubric=_rubric_items(raw.get("rubric", [])),
        tags=raw.get("tags", []),
    )
