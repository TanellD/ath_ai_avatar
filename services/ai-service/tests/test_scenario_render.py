"""Подстановка деталей под прогон — ath_contracts.render_scenario.

Функция живёт в контрактах, потому что подставляет gateway, а объявляет
методист через scenario-service; тесты здесь, потому что здесь же собирается
ответ модели, из которого берутся значения.
"""

from ath_contracts import (
    Mood,
    Persona,
    RubricItem,
    Scenario,
    ScenarioSlot,
    Stage,
    render_scenario,
    render_text,
    slot_defaults,
)

from app.llm.mock import MockLlmProvider
from app.scenario.drafts import build_details, build_scenario_draft
from app.scenario.prompts import build_details_schema

SLOTS = [
    ScenarioSlot(id="company", label="Компания", hint="закупщик", example="Северный Ветер"),
    ScenarioSlot(id="product", label="Продукт", hint="что продаём", example="CRM"),
]


def scenario(**patch: object) -> Scenario:
    base = {
        "id": "objection_price",
        "title": "Продажа {product}",
        "persona": Persona(
            name="Ирина",
            role="закупщик в «{company}»",
            character="скептична",
            mood=Mood.NEUTRAL,
            difficulty=3,
        ),
        "stages": [
            Stage(
                id="opening",
                goal="Выяснить, чем живёт {company}",
                agent_opening="Мы в «{company}» уже всё закупили.",
                completion_criteria="Сотрудник спросил про {product}",
                max_turns=4,
            )
        ],
        "rubric": [
            RubricItem(id="discovery", name="Выявление", description="Спрашивал про {product}")
        ],
        "briefing": "Вы продаёте {product} компании «{company}».",
        "slots": SLOTS,
    }
    return Scenario(**{**base, **patch})


def test_substitution_reaches_the_whole_scenario_not_just_the_briefing() -> None:
    """Иначе сотрудник прочтёт про «Северный Ветер», скажет это персонажу — а
    персонаж, собранный из неподставленной персоны, о такой компании не
    слышал."""
    rendered = render_scenario(scenario(), {"company": "Северный Ветер", "product": "CRM"})

    assert rendered.briefing == "Вы продаёте CRM компании «Северный Ветер»."
    assert rendered.persona.role == "закупщик в «Северный Ветер»"
    assert rendered.stages[0].agent_opening == "Мы в «Северный Ветер» уже всё закупили."
    assert rendered.stages[0].completion_criteria == "Сотрудник спросил про CRM"
    assert rendered.rubric[0].description == "Спрашивал про CRM"
    assert rendered.title == "Продажа CRM"


def test_identifiers_are_never_substituted() -> None:
    """По ним ходит автомат этапов, покрытие рубрики в отчёте и ссылки."""
    rendered = render_scenario(
        scenario(id="{company}"),
        {"company": "Северный Ветер"},
    )

    assert rendered.id == "{company}"
    assert rendered.stages[0].id == "opening"
    assert rendered.rubric[0].id == "discovery"


def test_stray_brace_in_methodist_text_does_not_blow_up() -> None:
    """Ровно поэтому здесь re.sub, а не str.format_map: одинокая скобка в
    тексте методиста уронила бы весь сценарий."""
    assert render_text("Скидка 20% {и ещё", {"company": "X"}) == "Скидка 20% {и ещё"


def test_unknown_placeholder_is_left_visible_instead_of_emptied() -> None:
    """Пустое место в тексте не отличить от задумки; «{company}» глазами
    видно и чинится."""
    assert render_text("Клиент — {company}.", {"other": "X"}) == "Клиент — {company}."


def test_no_values_leaves_the_scenario_untouched() -> None:
    """Сценарий без слотов — обычный статичный сценарий, и лишней копии
    объектов ему не нужно."""
    source = scenario()

    assert render_scenario(source, {}) is source


def test_defaults_come_from_the_slots_themselves() -> None:
    assert slot_defaults(scenario()) == {"company": "Северный Ветер", "product": "CRM"}


# ------------------------------------------------- сборка ответа модели


def test_missing_value_falls_back_to_the_example() -> None:
    """Дырка в подстановке оставила бы сотруднику «{company}» в тексте брифа,
    а персонажу — в промпте."""
    values = build_details({"values": {"product": "CRM для логистики"}}, SLOTS)

    assert values == {"company": "Северный Ветер", "product": "CRM для логистики"}


def test_blank_value_is_treated_as_missing() -> None:
    assert build_details({"values": {"company": "   ", "product": ""}}, SLOTS) == slot_defaults(
        scenario()
    )


def test_slot_ids_and_their_placeholders_are_renamed_together() -> None:
    """id слота приводится к слагу, как и остальные, но он ещё и стоит в
    тексте: разъехавшись, подстановка просто не сработает."""
    draft = build_scenario_draft(
        {
            "title": "Т",
            "persona": scenario().persona.model_dump(mode="json"),
            "stages": [scenario().stages[0].model_dump(mode="json")],
            "rubric": [scenario().rubric[0].model_dump(mode="json")],
            "tags": [],
            "briefing": "Вы продаёте в {Company-Name}.",
            "slots": [
                {"id": "Company-Name", "label": "Компания", "hint": "х", "example": "Y"}
            ],
        }
    )

    assert draft.slots[0].id == "company_name"
    assert draft.briefing == "Вы продаёте в {company_name}."


def test_placeholder_without_a_slot_gets_one() -> None:
    """Необъявленная подстановка иначе доедет до сотрудника фигурными
    скобками прямо в тексте."""
    draft = build_scenario_draft(
        {
            "title": "Т",
            "persona": scenario().persona.model_dump(mode="json"),
            "stages": [scenario().stages[0].model_dump(mode="json")],
            "rubric": [scenario().rubric[0].model_dump(mode="json")],
            "tags": [],
            "briefing": "Вы продаёте {product} в {company}.",
            "slots": [{"id": "company", "label": "Компания", "hint": "х", "example": "Y"}],
        }
    )

    assert {slot.id for slot in draft.slots} == {"company", "product"}


async def test_mock_provider_fills_every_declared_slot() -> None:
    raw = await MockLlmProvider().complete_json(
        system="", messages=[], model="mock", max_tokens=100, temperature=1.0,
        schema=build_details_schema(SLOTS),
    )

    assert set(build_details(raw, SLOTS)) == {"company", "product"}
