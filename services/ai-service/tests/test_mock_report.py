"""Заглушка LLM должна уметь отдавать отчёт, а не только классификацию.

Смысл проверки шире, чем «функция вернула словарь»: docker-compose по
умолчанию поднимается на `LLM_PROVIDER=mock` (обещание «стартует без ключей»),
и если заглушка не умеет отчёт, то весь путь завершения тренировки нельзя ни
показать, ни протестировать без платных ключей. Раньше `/evaluate` на mock
падал на отсутствующем `verdict`.

Главное здесь — цитаты: `build_report` отвергает `evidence`, которой нет в
репликах сотрудника, поэтому заглушка обязана цитировать настоящий транскрипт.
"""

from ath_contracts import Mood, Persona, RubricItem, Scenario, Stage, Turn, TurnRole

from app.evaluation.prompts import build_report_schema, build_transcript_message
from app.evaluation.report_builder import build_report
from app.llm.mock import MockLlmProvider

SCENARIO = Scenario(
    id="objection_price",
    title="Отработка возражения «дорого»",
    persona=Persona(
        name="Ирина", role="закупщик", character="скептична", mood=Mood.NEUTRAL
    ),
    stages=[
        Stage(
            id="opening",
            goal="Установить контакт",
            agent_opening="Здравствуйте.",
            completion_criteria="Представился",
            max_turns=3,
        )
    ],
    rubric=[
        RubricItem(id="discovery", name="Выявление потребности", description="..."),
        RubricItem(id="objection", name="Работа с возражением", description="..."),
    ],
)

TRANSCRIPT = [
    Turn(
        role=TurnRole.AGENT,
        text="Здравствуйте, у меня десять минут.",
        stage_id="opening",
        ts=0.0,
    ),
    Turn(
        role=TurnRole.USER,
        text="Здравствуйте, меня зовут Пётр. А сколько вы сейчас тратите в месяц?",
        stage_id="opening",
        ts=1.0,
    ),
]


async def test_mock_report_passes_report_builder() -> None:
    """Ответ заглушки должен пройти те же проверки, что и ответ настоящей модели."""
    provider = MockLlmProvider()

    raw = await provider.complete_json(
        system="",
        messages=[{"role": "user", "content": build_transcript_message(TRANSCRIPT)}],
        model="mock",
        max_tokens=1000,
        temperature=0.0,
        schema=build_report_schema(SCENARIO),
    )

    report = build_report(
        session_id="s1",
        scenario=SCENARIO,
        transcript=TRANSCRIPT,
        raw=raw,
        duration_sec=60,
        stages_completed=1,
        stages_total=1,
    )

    # Покрыты все критерии рубрики — иначе build_report бы не пропустил.
    assert {s.criterion_id for s in report.scores} == {"discovery", "objection"}
    # И цитата — настоящая реплика сотрудника, а не выдумка заглушки.
    assert report.scores[0].evidence in TRANSCRIPT[1].text


async def test_report_carries_scenario_and_model() -> None:
    """Без scenario_id экран отчёта не подтянет рубрику и покажет id критериев;
    без model отчёт заглушки не отличить от настоящего."""
    provider = MockLlmProvider()
    raw = await provider.complete_json(
        system="",
        messages=[{"role": "user", "content": build_transcript_message(TRANSCRIPT)}],
        model="mock",
        max_tokens=1000,
        temperature=0.0,
        schema=build_report_schema(SCENARIO),
    )

    report = build_report(
        session_id="s1",
        scenario=SCENARIO,
        transcript=TRANSCRIPT,
        raw=raw,
        duration_sec=60,
        stages_completed=1,
        stages_total=1,
        model="mock/claude-opus-5",
    )

    assert report.scenario_id == SCENARIO.id
    assert report.model.startswith("mock"), "по этому признаку рисуется плашка в UI"


async def test_mock_still_answers_classification() -> None:
    """Схема классификации не должна пострадать от появления отчёта."""
    provider = MockLlmProvider()

    raw = await provider.complete_json(
        system="",
        messages=[],
        model="mock",
        max_tokens=100,
        temperature=0.0,
        schema={"properties": {"classification": {}, "reason": {}}},
    )

    assert raw["classification"] == "incomplete"
