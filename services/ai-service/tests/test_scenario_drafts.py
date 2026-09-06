"""Черновики сценария — Claude.md §7.

Как и в test_prompts.py, проверяются инварианты, а не формулировки: тексты
промптов будут меняться, а «критерий классификатора не утекает сотруднику» и
«идентификаторы не повторяются» меняться не должны.
"""

from ath_contracts import Mood, Persona, Stage
from ath_contracts.api import ScenarioDraftResponse

from app.llm.mock import MockLlmProvider
from app.scenario.drafts import build_rubric_draft, build_scenario_draft
from app.scenario.prompts import (
    build_draft_schema,
    build_draft_system,
    build_rubric_message,
    build_rubric_schema,
    build_rubric_system,
)

PERSONA = Persona(
    name="Ирина",
    role="закупщик среднего бизнеса",
    character="скептична, перебивает, торгуется",
    mood=Mood.NEUTRAL,
    difficulty=3,
)

STAGES = [
    Stage(
        id="opening",
        goal="Установить контакт",
        agent_opening="Здравствуйте. У меня десять минут.",
        completion_criteria="Сотрудник представился и задал открытый вопрос",
        max_turns=4,
    )
]


# --------------------------------------------------------------- промпты


def test_generator_is_told_that_criteria_stay_hidden_from_the_trainee() -> None:
    """Иначе модель напишет completion_criteria как подсказку сотруднику —
    ScenarioPreview специально их не показывает (docs/bugs_front.md №8)."""
    system = build_draft_system()

    assert "не показывается" in system.lower() or "не видна" in system.lower()
    assert "классификатор" in system.lower()


def test_generator_is_told_the_code_moves_between_stages() -> None:
    """Свободная навигация моделью — прямо запрещённое решение (§5)."""
    assert "переход между этапами делает код" in build_draft_system().lower()


def test_rubric_prompt_demands_quotable_behaviour() -> None:
    """Критерий, который нечем процитировать, ломает главную гипотезу проекта:
    под каждым баллом обязана стоять дословная цитата (§7)."""
    system = build_rubric_system()

    assert "цитат" in system.lower()
    assert "наблюдаемое" in system.lower()


def test_rubric_message_carries_the_stages_it_must_score() -> None:
    message = build_rubric_message("Возражение «дорого»", PERSONA, STAGES, 4)

    assert "Ирина" in message
    assert "Установить контакт" in message


# ----------------------------------------------------------------- схемы


def test_schema_pins_the_requested_counts() -> None:
    """Методист просит конкретное число этапов и критериев — схемой это
    гарантируется, а не просьбой в тексте."""
    schema = build_draft_schema(stages_count=3, rubric_count=5)

    assert schema["properties"]["stages"]["minItems"] == 3
    assert schema["properties"]["stages"]["maxItems"] == 3
    assert schema["properties"]["rubric"]["minItems"] == 5
    assert schema["properties"]["rubric"]["maxItems"] == 5


def test_schema_pins_mood_to_the_contract_enum() -> None:
    """Значение вне Mood контракт всё равно отвергнет — не доводим до этого."""
    mood = build_draft_schema(1, 1)["properties"]["persona"]["properties"]["mood"]

    assert set(mood["enum"]) == {m.value for m in Mood}


# ------------------------------------------------- сборка из сырого ответа


def test_unusable_ids_become_slugs() -> None:
    """Модель охотно вернёт «Работа с возражением» или «objection-handling».
    Такой id уходит в адрес страницы и в ключ БД, и его нельзя показывать
    методисту ошибкой в поле, которое заполнил не он."""
    draft = build_rubric_draft(
        {
            "items": [
                {
                    "id": "Objection-Handling",
                    "name": "Работа с возражением",
                    "description": "Обосновал ценность",
                    "scale": 5,
                    "weight": 1.0,
                }
            ]
        }
    )

    assert draft.items[0].id == "objection_handling"


def test_id_that_slugs_to_nothing_falls_back_to_a_position() -> None:
    """Кириллический id даёт пустой слаг — терять из-за этого критерий нельзя."""
    draft = build_rubric_draft(
        {
            "items": [
                {"id": "возражение", "name": "Н", "description": "О", "scale": 5, "weight": 1.0}
            ]
        }
    )

    assert draft.items[0].id == "criterion_1"


def test_duplicate_ids_are_separated_instead_of_dropped() -> None:
    """Схема дубликаты не запрещает, а ломаются они молча: дубликат stage.id
    схлопывает словарь StageMachine, дубликат rubric[].id отбраковывает отчёт
    уже после пройденной сессии."""
    item = {"name": "Н", "description": "О", "scale": 5, "weight": 1.0}
    draft = build_rubric_draft({"items": [{**item, "id": "closing"}, {**item, "id": "closing"}]})

    assert [i.id for i in draft.items] == ["closing", "closing_2"]
    assert len(draft.items) == 2, "второй критерий не должен теряться"


def test_stage_ids_are_deduplicated_too() -> None:
    stage = {
        "goal": "Ц",
        "agent_opening": "Р",
        "completion_criteria": "К",
        "max_turns": 4,
    }
    draft = build_scenario_draft(
        {
            "title": "Т",
            "persona": PERSONA.model_dump(mode="json"),
            "stages": [{**stage, "id": "opening"}, {**stage, "id": "opening"}],
            "rubric": [{"id": "a", "name": "Н", "description": "О", "scale": 5, "weight": 1.0}],
            "tags": [],
        }
    )

    assert [s.id for s in draft.stages] == ["opening", "opening_2"]


# ------------------------------------------------------- сквозь заглушку


async def test_mock_provider_produces_a_valid_scenario_draft() -> None:
    """Заглушка обязана проходить те же проверки, что и настоящий провайдер:
    на ней проверяется весь путь кнопки без ключей."""
    raw = await MockLlmProvider().complete_json(
        system="", messages=[], model="mock", max_tokens=100, temperature=0.0,
        schema=build_draft_schema(stages_count=2, rubric_count=3),
    )

    draft = build_scenario_draft(raw)

    assert isinstance(draft, ScenarioDraftResponse)
    assert len(draft.stages) == 2
    assert len(draft.rubric) == 3


async def test_mock_provider_produces_a_valid_rubric_draft() -> None:
    raw = await MockLlmProvider().complete_json(
        system="", messages=[], model="mock", max_tokens=100, temperature=0.0,
        schema=build_rubric_schema(4),
    )

    assert len(build_rubric_draft(raw).items) == 4
