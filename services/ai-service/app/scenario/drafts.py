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
from collections.abc import Callable

from ath_contracts import Persona, RubricItem, ScenarioSlot, Stage
from ath_contracts.api import RubricDraft, ScenarioDraftResponse


class InvalidDraftError(ValueError):
    """Черновик не прошёл проверку формы и не должен уходить в форму редактора.

    Тот же принцип, что `InvalidReportError` в `evaluation/report_builder.py`:
    `complete_json()` типизирован как `dict`, но это контракт, а не гарантия — модель
    может ответить JSON-массивом или скаляром. `_build` (`api/scenario.py`) ловит этот
    тип наравне с `ValidationError` и отдаёт 502 «попробуйте ещё раз», а не 500 на
    `AttributeError` от `raw.get(...)` на не-словаре.
    """


def _require_dict(raw: object, what: str) -> dict:
    if not isinstance(raw, dict):
        raise InvalidDraftError(f"{what}: ответ модели не JSON-объект ({type(raw).__name__})")
    return raw


def _require_list(raw: dict, key: str) -> list:
    value = raw.get(key, [])
    if not isinstance(value, list):
        raise InvalidDraftError(f"{key!r}: ожидался список, пришло {type(value).__name__}")
    return value


_NON_SLUG = re.compile(r"[^a-z0-9]+")

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
"""Тот же шаблон, что у `ath_contracts.render_text`: только такие подстановки
gateway и подставит."""

_REPAIRABLE = re.compile(r"\{([\w\- ]+)\}")
"""Шире предыдущего — намеренно.

Модель пишет в текст `{Company-Name}` под стать своему же id слота. Дефис не
подходит ни в идентификатор, ни под `_PLACEHOLDER`, поэтому такую подстановку
надо не просто пропустить, а починить вместе с id — иначе после приведения
слота к слагу текст и слот разъедутся, и сотрудник прочитает фигурные скобки.
"""


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
    raw = _require_dict(raw, "rubric")
    return RubricDraft(items=_rubric_items(_require_list(raw, "items")))


def build_details(raw: dict, slots: list[ScenarioSlot]) -> dict[str, str]:
    """Значения слотов, где на каждый объявленный слот что-то есть.

    Пропущенный или пустой ключ закрывается `example` самого слота: дырка в
    подстановке оставила бы сотруднику «{company}» прямо в тексте брифа, а
    персонажу — в промпте. Своих ключей, которых методист не объявлял, здесь
    быть не может: подставлять их всё равно некуда.
    """
    raw = _require_dict(raw, "details")
    values = raw.get("values") or {}
    return {
        slot.id: str(values.get(slot.id) or slot.example).strip() or slot.example
        for slot in slots
    }


_TEXT_FIELDS = {
    "stage": ("goal", "agent_opening", "completion_criteria"),
    "rubric": ("name", "description"),
    "persona": ("name", "role", "character"),
}
"""Поля, по которым идёт подстановка, — те же, что у `render_scenario`.

Идентификаторы сюда не входят никогда: по ним ходит автомат этапов, покрытие
рубрики в отчёте и ссылки.
"""


def _slot_renames(raw_slots: list[dict], ids: list[str]) -> dict[str, str]:
    return {str(slot.get("id", "")): new for slot, new in zip(raw_slots, ids, strict=True)}


def _repairer(renames: dict[str, str]) -> Callable[[str], str]:
    def repair(match: re.Match[str]) -> str:
        name = match.group(1)
        return "{" + (renames.get(name) or _slug(name, name)) + "}"

    return lambda text: _REPAIRABLE.sub(repair, text or "")


def _fix(raw_item: dict, fields: tuple[str, ...], repair: Callable[[str], str]) -> dict:
    return {**raw_item, **{field: repair(raw_item.get(field, "")) for field in fields}}


def build_scenario_draft(raw: dict) -> ScenarioDraftResponse:
    """Черновик, у которого подстановки и слоты сходятся между собой.

    Два расхождения схема допускает, а сотрудник увидит глазами:

    - id слота приходится приводить к слагу, как и остальные, — но он ещё и
      стоит в тексте как `{id}`. Переименовываем слот и подстановки вместе,
      иначе значение просто не подставится;
    - подстановка без объявленного слота остаётся в тексте как есть, и
      сотрудник читает «Вы продаёте {product}». Объявляем такой слот
      заготовкой: методист увидит в форме недописанную строку и допишет её —
      это лучше, чем фигурные скобки в тексте у сотрудника.

    Чинится ВЕСЬ текст, а не только бриф. Живой ответ модели на первой же
    проверке разложил пять слотов по трём местам: `{clinic_name}` — и в бриф, и
    в реплику этапа, `{appointment_time}` и `{new_time}` — только в реплики
    этапов, в брифе их нет вовсе. Правь мы один бриф, переименованный слот
    разъехался бы ровно с тем текстом, который персонаж произносит вслух.
    """
    raw = _require_dict(raw, "draft")
    raw_slots = _require_list(raw, "slots")
    slot_ids = _unique_ids(raw_slots, "slot")
    repair = _repairer(_slot_renames(raw_slots, slot_ids))

    raw_stages = _require_list(raw, "stages")
    stage_ids = _unique_ids(raw_stages, "stage")

    draft = ScenarioDraftResponse(
        title=repair(raw.get("title", "")),
        persona=Persona.model_validate(
            _fix(raw.get("persona", {}), _TEXT_FIELDS["persona"], repair)
        ),
        stages=[
            Stage.model_validate({**_fix(stage, _TEXT_FIELDS["stage"], repair), "id": stage_id})
            for stage, stage_id in zip(raw_stages, stage_ids, strict=True)
        ],
        rubric=_rubric_items(
            [_fix(item, _TEXT_FIELDS["rubric"], repair) for item in _require_list(raw, "rubric")]
        ),
        tags=raw.get("tags", []),
        briefing=repair(raw.get("briefing", "")),
        slots=[
            ScenarioSlot.model_validate({**slot, "id": slot_id})
            for slot, slot_id in zip(raw_slots, slot_ids, strict=True)
        ],
    )

    return draft.model_copy(update={"slots": _with_missing_slots(draft)})


def _with_missing_slots(draft: ScenarioDraftResponse) -> list[ScenarioSlot]:
    """Заготовки под подстановки, которые модель забыла объявить."""
    declared = {slot.id for slot in draft.slots}
    extra = [
        name
        for name in dict.fromkeys(_PLACEHOLDER.findall(_all_text(draft)))
        if name not in declared
    ]
    return [
        *draft.slots,
        *(ScenarioSlot(id=name, label=name, hint=name, example=name) for name in extra),
    ]


def _all_text(draft: ScenarioDraftResponse) -> str:
    parts = [draft.title, draft.briefing]
    parts += [getattr(draft.persona, field) for field in _TEXT_FIELDS["persona"]]
    parts += [getattr(stage, f) for stage in draft.stages for f in _TEXT_FIELDS["stage"]]
    parts += [getattr(item, f) for item in draft.rubric for f in _TEXT_FIELDS["rubric"]]
    # Разделитель любой, лишь бы не склеивал слова: текст здесь только
    # сканируется на подстановки, а не читается.
    return " ".join(parts)
