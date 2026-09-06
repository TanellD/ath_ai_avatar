"""Черновики сценария — Claude.md §7.

Как и в test_prompts.py, проверяются инварианты, а не формулировки: тексты
промптов будут меняться, а «критерий классификатора не утекает сотруднику» и
«идентификаторы не повторяются» меняться не должны.
"""

import pytest
from ath_contracts import Mood, Persona, RubricItem, Stage
from ath_contracts.api import ScenarioDraftResponse

from app.llm.mock import MockLlmProvider
from app.scenario.drafts import InvalidDraftError, build_rubric_draft, build_scenario_draft
from app.scenario.prompts import (
    build_draft_message,
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
    ScenarioPreview специально их не показывает (docs/bugs/bugs_front.md №8)."""
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


def test_schema_requires_a_suggested_id_shaped_like_an_identifier() -> None:
    """Без pattern модель охотно вернёт «Отработка возражения дорого» — такое
    не годится в адрес страницы (см. drafts.py::_scenario_id)."""
    suggested_id = build_draft_schema(1, 1)["properties"]["suggested_id"]

    assert suggested_id["pattern"] == "^[a-z0-9_]+$"


def test_draft_system_asks_to_translate_not_transliterate_the_id() -> None:
    """«otrabotka_vozrazheniya» технически латиница, но не «на английском» —
    и не то, что просил методист."""
    system = build_draft_system().lower()

    assert "suggested_id" in system
    assert "переведи" in system


def test_unset_counts_give_the_model_a_range_instead_of_one() -> None:
    """`stages_count=None` значит «методист не задавал число» — на пустом
    бланке форма даёт 1 (длина emptyStage()), и без диапазона черновик
    приходил бы ровно с одним этапом и одним критерием."""
    schema = build_draft_schema(stages_count=None, rubric_count=None)

    assert schema["properties"]["stages"]["minItems"] > 1
    assert schema["properties"]["stages"]["maxItems"] > schema["properties"]["stages"]["minItems"]
    assert schema["properties"]["rubric"]["minItems"] > 1


def test_one_count_set_and_the_other_auto_are_independent() -> None:
    """Методист может зафиксировать только этапы или только критерии."""
    schema = build_draft_schema(stages_count=5, rubric_count=None)

    assert schema["properties"]["stages"]["minItems"] == 5
    assert schema["properties"]["stages"]["maxItems"] == 5
    assert schema["properties"]["rubric"]["minItems"] != schema["properties"]["rubric"]["maxItems"]


# ------------------------------------------------------- опора на форму


def test_auto_count_message_names_a_range_not_a_round_number() -> None:
    message = build_draft_message("Тест", stages_count=None, rubric_count=None)

    assert "Сделай" in message
    assert "3" in message and "6" in message


def test_auto_count_explanation_is_not_duplicated() -> None:
    """Оба поля обычно «Авто» — это дефолт формы, самый частый вызов кнопки.
    Формула на два поля когда-то склеивала два одинаковых пояснения подряд
    в одном предложении — неряшливый промпт, не ошибка модели, но такое же
    реальное качество текста, которое видит модель."""
    message = build_draft_message("Тест", stages_count=None, rubric_count=None)

    assert message.count("реши сам") == 1


def test_mixed_counts_attach_the_auto_note_to_the_right_field() -> None:
    """Этапы заданы явно, критерии — авто: пояснение «реши сам» обязано
    называть критерии, а не повиснуть непонятно к чему на смешанном вводе."""
    message = build_draft_message("Тест", stages_count=4, rubric_count=None)

    assert message.count("реши сам") == 1
    assert "критери" in message.lower().split("реши сам")[0][-40:]
    assert "этап" not in message.lower().split("реши сам")[0][-40:]


def test_current_form_state_is_not_sent_when_form_is_blank() -> None:
    """Пустая заготовка формы (пустые emptyStage()/emptyRubricItem()) не
    должна попасть в промпт как будто это требование методиста."""
    blank = ScenarioDraftResponse(
        title="",
        persona=Persona(name="", role="", character=""),
        stages=[Stage(id="stage_1", goal="", agent_opening="", completion_criteria="")],
        rubric=[RubricItem(id="criterion_1", name="", description="")],
    )

    message = build_draft_message("Тест", None, None, current=blank)

    assert "уже заполнил" not in message.lower()


def test_current_form_state_is_carried_into_the_message() -> None:
    """Методист поправил персонажа руками и просит пересобрать остальное —
    модель обязана увидеть эту правку, а не начать с нуля."""
    current = ScenarioDraftResponse(
        title="Возражение по цене",
        persona=PERSONA,
        stages=[Stage(id="stage_1", goal="", agent_opening="", completion_criteria="")],
        rubric=[RubricItem(id="criterion_1", name="", description="")],
    )

    message = build_draft_message("Тест", None, None, current=current)

    assert "уже заполнил" in message.lower()
    assert "Ирина" in message
    assert "не противоречь" in message.lower()


def test_current_stages_are_numbered_consecutively_skipping_blanks() -> None:
    """Между двумя заполненными этапами в форме может стоять пустая заготовка
    (добавили строку, не успели заполнить). Нумерация по позиции в форме дала
    бы «1. ... 3. ...» без «2.» — модель решила бы, что этап потерялся, а не
    что его ещё не заполнили."""
    current = ScenarioDraftResponse(
        title="Т",
        persona=PERSONA,
        stages=[
            Stage(id="s1", goal="Установить контакт", agent_opening="", completion_criteria=""),
            Stage(id="s2", goal="", agent_opening="", completion_criteria=""),
            Stage(id="s3", goal="Закрыть сделку", agent_opening="", completion_criteria=""),
        ],
        rubric=[RubricItem(id="criterion_1", name="", description="")],
    )

    message = build_draft_message("Тест", None, None, current=current)

    assert "1. цель «Установить контакт»" in message
    assert "2. цель «Закрыть сделку»" in message
    assert "3." not in message.split("Критерии:")[0]


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


def _minimal_raw(**overrides: object) -> dict:
    stage = {
        "goal": "Ц",
        "agent_opening": "Р",
        "completion_criteria": "К",
        "max_turns": 4,
        "id": "opening",
    }
    return {
        "title": "Т",
        "persona": PERSONA.model_dump(mode="json"),
        "stages": [stage],
        "rubric": [{"id": "a", "name": "Н", "description": "О", "scale": 5, "weight": 1.0}],
        "tags": [],
        **overrides,
    }


def test_suggested_id_is_slugged_like_any_other_identifier() -> None:
    draft = build_scenario_draft(_minimal_raw(suggested_id="Price Objection!!"))

    assert draft.suggested_id == "price_objection"


def test_suggested_id_falls_back_to_the_title_when_missing() -> None:
    """Не каждый провайдер уважает `required` в схеме (докстринг файла) —
    методист не должен получить пустое поле «Идентификатор» из-за этого."""
    draft = build_scenario_draft(_minimal_raw(title="Price Objection", suggested_id=""))

    assert draft.suggested_id == "price_objection"


def test_suggested_id_falls_back_to_a_placeholder_when_nothing_is_latin() -> None:
    """И suggested_id, и title — кириллица вопреки просьбе перевести смысл:
    методист получает пустое поле, только если и заглушка бы не сработала —
    а не пустое поле вообще."""
    draft = build_scenario_draft(
        _minimal_raw(title="Возражение по цене", suggested_id="возражение_по_цене")
    )

    assert draft.suggested_id == "scenario"


# ---------------------------------------------------- устойчивый разбор
#
# Тот же принцип, что в evaluation/report_builder.py (PR #32): complete_json()
# типизирован как dict, но это контракт, а не гарантия. Не-объект от модели
# обязан дать один тип ошибки, который вызывающий (_build в api/scenario.py)
# уже умеет превращать в 502, а не в AttributeError → 500.


def test_scenario_draft_rejects_a_non_object_response() -> None:
    with pytest.raises(InvalidDraftError):
        build_scenario_draft(["not", "an", "object"])


def test_rubric_draft_rejects_a_non_object_response() -> None:
    with pytest.raises(InvalidDraftError):
        build_rubric_draft("not an object")


def test_scenario_draft_rejects_stages_that_are_not_a_list() -> None:
    """Схема это гарантирует, но schema — не гарантия (см. докстринг файла)."""
    with pytest.raises(InvalidDraftError):
        build_scenario_draft(
            {
                "title": "Т",
                "persona": PERSONA.model_dump(mode="json"),
                "stages": "не список",
                "rubric": [{"id": "a", "name": "Н", "description": "О"}],
                "tags": [],
            }
        )


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
    assert draft.suggested_id  # непустой, форма должна получить что подставить


async def test_mock_provider_produces_a_valid_rubric_draft() -> None:
    raw = await MockLlmProvider().complete_json(
        system="", messages=[], model="mock", max_tokens=100, temperature=0.0,
        schema=build_rubric_schema(4),
    )

    assert len(build_rubric_draft(raw).items) == 4


async def test_mock_provider_handles_auto_counts_too() -> None:
    """Кнопка на пустом бланке шлёт `stages_count=None` — заглушка обязана
    пройти и этот путь, не только явное число."""
    raw = await MockLlmProvider().complete_json(
        system="", messages=[], model="mock", max_tokens=100, temperature=0.0,
        schema=build_draft_schema(stages_count=None, rubric_count=None),
    )

    draft = build_scenario_draft(raw)

    assert len(draft.stages) > 1
    assert len(draft.rubric) > 1
