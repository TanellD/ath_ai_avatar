"""Промпты и схемы генерации черновиков методисту — Claude.md §7.

Схемы строятся ИЗ ВХОДА, а не берутся статическими — та же идиома, что в
`evaluation/prompts.py::build_report_schema`. Там enum реальных id рубрики не
даёт модели изобрести несуществующий критерий; здесь `minItems`/`maxItems`
жёстко фиксируют количество этапов и критериев, а перечисление настроений не
даёт вернуть значение вне `Mood`. Всё, что можно ограничить схемой, здесь
ограничено схемой, а не просьбой в тексте.

Чего схема не гарантирует — проверяется кодом в `drafts.py`: `pattern` для id
шлюз может проигнорировать, а «идентификаторы должны быть разными» модель
может нарушить, не нарушив схему.
"""

from ath_contracts import Persona, ScenarioSlot, Stage

_PERSONA_BLOCK = """\
Персонаж: {name} ({role}). Манера: {character}. Сложность {difficulty} из 5.
"""

_STAGES_BLOCK = """\
Этапы разговора:
{stages}
"""

_METHODOLOGY = """\
Как устроен тренажёр, чтобы черновик был рабочим:

- Инициативу держит персонаж: он спрашивает, ведёт по этапам и дожимает
  неполные ответы. Оценивается сотрудник, а не персонаж.
- Переход между этапами делает код, а не модель. `completion_criteria` —
  формулировка для классификатора: по ней он отвечает «зачтено / неполно / не
  по теме». Пиши её проверяемо и об одном («сотрудник назвал конкретный срок»),
  а не оценочно («сотрудник хорошо поработал»).
- `completion_criteria` сотруднику НЕ показывается: это не подсказка с
  правильными фразами. `goal` и описание критерия рубрики — показываются, и
  отвечают на «что здесь вообще происходит».
- `agent_opening` — живая реплика персонажа в первом лице, которой он
  открывает этап. Не описание этапа и не ремарка.
"""

_RUBRIC_RULES = """\
Правила для рубрики:

- Критерий описывает НАБЛЮДАЕМОЕ поведение сотрудника в этом разговоре, а не
  черту характера: «задавал открытые вопросы до презентации», а не
  «клиентоориентирован». Под каждый балл отчёт обязан привести дословную
  цитату из реплики сотрудника — критерий, который нечем процитировать,
  бесполезен.
- Критерии не пересекаются: одно и то же поведение не оценивается дважды.
- `weight` больше единицы — только тому, ради чего тренировка и затевалась.
- `scale` — 5, если нет причины иначе.
"""

_ID_RULES = """\
Идентификаторы (`id` этапов, критериев и слотов): латиница в нижнем регистре,
цифры и подчёркивание, коротко и по смыслу (`opening`, `objection_handling`,
`company`). Внутри списка они не повторяются.
"""

_BRIEFING_RULES = """\
Правила для брифа (`briefing` и `slots`) — это то, что сотрудник читает перед
разговором:

- `briefing` — три-пять предложений от второго лица: где сотрудник, кто перед
  ним, чего этот человек хочет и чего хочет добиться сам сотрудник. Обстановка,
  а не инструкция: приёмов и правильных фраз в нём быть не должно.
- Конкретные детали — имена, названия компаний, продукты, цифры — не пиши в
  текст напрямую, а поставь на их место подстановку `{имя_слота}` и объяви
  слот. Эти детали подбираются заново на каждый прогон, чтобы одна и та же
  тренировка не была одинаковой на пятый раз.
- В `hint` слота напиши, что именно нужно придумать («название компании-
  закупщика, средний бизнес»), а в `example` — правдоподобный пример.
- Слотов немного: три-пять. Имя самого персонажа слотом делать не нужно —
  оно задано в `persona`.
- Каждая подстановка в тексте обязана иметь объявленный слот, и наоборот.
"""

_DRAFT_SYSTEM = """\
Ты — методист корпоративного обучения. По короткому описанию собери черновик
сценария речевой тренировки: персонажа, этапы разговора, рубрику оценки и
бриф, который сотрудник читает перед разговором.

{methodology}
{rubric_rules}
{briefing_rules}
{id_rules}
Черновик пойдёт человеку на правку, поэтому лучше конкретно и коротко, чем
обтекаемо и длинно. Пиши по-русски.
"""

_RUBRIC_SYSTEM = """\
Ты — методист корпоративного обучения. Персонаж и этапы разговора уже описаны —
собери к ним рубрику оценки.

{rubric_rules}
{id_rules}
Оценивай ровно то, что этот разговор может показать: критерий, для которого в
этапах нет повода проявиться, не нужен. Пиши по-русски.
"""

_MOODS = ["neutral", "irritated", "friendly"]

_ID_PATTERN = "^[a-z0-9_]+$"


def _persona_block(persona: Persona) -> str:
    return _PERSONA_BLOCK.format(
        name=persona.name,
        role=persona.role,
        character=persona.character,
        difficulty=persona.difficulty,
    )


def _stages_block(stages: list[Stage]) -> str:
    lines = [
        f"{index}. {stage.goal} — персонаж открывает его так: «{stage.agent_opening}». "
        f"Зачтено, когда: {stage.completion_criteria}"
        for index, stage in enumerate(stages, start=1)
    ]
    return _STAGES_BLOCK.format(stages="\n".join(lines))


def build_draft_system() -> str:
    return _DRAFT_SYSTEM.format(
        methodology=_METHODOLOGY,
        rubric_rules=_RUBRIC_RULES,
        briefing_rules=_BRIEFING_RULES,
        id_rules=_ID_RULES,
    )


def build_draft_message(brief: str, stages_count: int, rubric_count: int) -> str:
    return (
        f"Описание тренировки от методиста:\n{brief}\n\n"
        f"Сделай {stages_count} этап(ов) и {rubric_count} критери(ев) оценки."
    )


def build_rubric_system() -> str:
    return _RUBRIC_SYSTEM.format(rubric_rules=_RUBRIC_RULES, id_rules=_ID_RULES)


def build_rubric_message(title: str, persona: Persona, stages: list[Stage], count: int) -> str:
    return (
        f"Сценарий: «{title}».\n"
        f"{_persona_block(persona)}\n"
        f"{_stages_block(stages)}\n"
        f"Собери {count} критери(ев) оценки."
    )


def _rubric_items_schema(count: int) -> dict:
    """`minItems == maxItems == count` — методист просил конкретное число."""
    return {
        "type": "array",
        "minItems": count,
        "maxItems": count,
        "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "pattern": _ID_PATTERN},
                "name": {"type": "string", "minLength": 1},
                "description": {"type": "string", "minLength": 1},
                "scale": {"type": "integer", "minimum": 2},
                "weight": {"type": "number", "exclusiveMinimum": 0},
            },
            "required": ["id", "name", "description", "scale", "weight"],
            "additionalProperties": False,
        },
    }


def _stages_schema(count: int) -> dict:
    return {
        "type": "array",
        "minItems": count,
        "maxItems": count,
        "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "pattern": _ID_PATTERN},
                "goal": {"type": "string", "minLength": 1},
                "agent_opening": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Реплика персонажа в первом лице",
                },
                "completion_criteria": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Формулировка для классификатора, сотруднику не видна",
                },
                "max_turns": {"type": "integer", "minimum": 1},
            },
            "required": ["id", "goal", "agent_opening", "completion_criteria", "max_turns"],
            "additionalProperties": False,
        },
    }


def build_rubric_schema(count: int) -> dict:
    return {
        "type": "object",
        "properties": {"items": _rubric_items_schema(count)},
        "required": ["items"],
        "additionalProperties": False,
    }


_DETAILS_SYSTEM = """\
Ты придумываешь детали для тренировочного разговора: имена, названия компаний,
продукты, цифры.

Правила:

- Каждое значение — короткое, как в жизни: «Северный Ветер», «CRM для
  логистики», «двадцать процентов». Не предложение и не пояснение.
- Значения должны сочетаться между собой и с ролью персонажа: компания,
  продукт и цифры — из одного правдоподобного мира.
- Не бери названия реальных компаний и имена реальных людей.
- Значение подставляется прямо в текст вместо {id_слота}, поэтому пиши его в
  той форме, в какой оно должно там стоять. Кавычек вокруг не добавляй.

Пиши по-русски.
"""


def build_details_system() -> str:
    return _DETAILS_SYSTEM


def build_details_message(title: str, persona_role: str, briefing: str) -> str:
    """Скелет брифа даётся целиком: из него видно, куда попадёт каждое
    значение и в каком падеже оно должно там стоять."""
    return (
        f"Тренировка: «{title}». Собеседник — {persona_role}.\n\n"
        f"Текст, в который подставятся значения:\n{briefing}"
    )


def build_details_schema(slots: list[ScenarioSlot]) -> dict:
    """Ключи фиксированы объявленными слотами.

    Тот же приём, что с enum'ом id рубрики в build_report_schema: лишнего ключа
    модель не придумает, а `required` не даст пропустить нужный — подстановка
    останется без дырок.
    """
    return {
        "type": "object",
        "properties": {
            "values": {
                "type": "object",
                "properties": {
                    slot.id: {"type": "string", "minLength": 1, "description": slot.hint}
                    for slot in slots
                },
                "required": [slot.id for slot in slots],
                "additionalProperties": False,
            }
        },
        "required": ["values"],
        "additionalProperties": False,
    }


def build_draft_schema(stages_count: int, rubric_count: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1},
            "persona": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "role": {"type": "string", "minLength": 1},
                    "character": {"type": "string", "minLength": 1},
                    # Значения Mood перечислены схемой, а не выпрошены текстом:
                    # контракт всё равно отвергнет что-либо ещё.
                    "mood": {"type": "string", "enum": _MOODS},
                    "difficulty": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                "required": ["name", "role", "character", "mood", "difficulty"],
                "additionalProperties": False,
            },
            "stages": _stages_schema(stages_count),
            "rubric": _rubric_items_schema(rubric_count),
            "tags": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "briefing": {"type": "string", "minLength": 1},
            "slots": {
                "type": "array",
                "minItems": 1,
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "pattern": _ID_PATTERN},
                        "label": {"type": "string", "minLength": 1},
                        "hint": {"type": "string", "minLength": 1},
                        "example": {"type": "string", "minLength": 1},
                    },
                    "required": ["id", "label", "hint", "example"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["title", "persona", "stages", "rubric", "tags", "briefing", "slots"],
        "additionalProperties": False,
    }
