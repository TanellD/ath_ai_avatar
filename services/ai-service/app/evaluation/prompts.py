"""Промпт итоговой оценки — Claude.md §7.

Отчёт — интерфейс методиста, и он главный. Каждый балл обязан быть проверяем за
десять секунд, иначе методист начнёт перечитывать историю целиком и продукт
потеряет смысл.

Отсюда единственное действительно жёсткое требование к этому промпту:
**цитировать дословно.** Пересказ вместо цитаты выглядит убедительно и
разрушает проверяемость незаметно — методист не может сверить пересказ с
транскриптом, а значит не может проверить балл.
"""

from ath_contracts import Scenario, Turn

_EVALUATION_SYSTEM = """\
Ты — методист, оценивающий запись тренировочного диалога.

Сотрудник проходил сценарий «{title}», разговаривая с персонажем {persona_name}
({persona_role}).

Оцени работу сотрудника по каждому критерию рубрики.

Обязательные правила:

1. Под каждым баллом приводи ПОЛЕ evidence — дословную цитату из реплики
   СОТРУДНИКА. Копируй текст посимвольно из транскрипта. Не перефразируй, не
   сокращай, не исправляй оговорки и не соединяй две реплики в одну.
2. Если подтверждающей цитаты в транскрипте нет — ставь низкий балл и цитируй
   ту реплику, которая ближе всего к теме критерия. Придумывать цитату нельзя
   ни при каких условиях.
3. Оценивай только реплики сотрудника (role = user). Реплики персонажа —
   контекст, а не предмет оценки.
4. verdict — две-три строки живым языком: что получается, что нет.
5. comment под баллом — одна фраза, почему поставлен именно этот балл.

Шкала каждого критерия указана в рубрике. total_score — среднее по критериям с
учётом весов.

Рубрика:
{rubric}
"""


def build_evaluation_system(scenario: Scenario) -> str:
    rubric_lines = [
        f"- {item.id} «{item.name}» (шкала 0-{item.scale}, вес {item.weight}): {item.description}"
        for item in scenario.rubric
    ]
    return _EVALUATION_SYSTEM.format(
        title=scenario.title,
        persona_name=scenario.persona.name,
        persona_role=scenario.persona.role,
        rubric="\n".join(rubric_lines),
    )


def build_transcript_message(transcript: list[Turn]) -> str:
    """Транскрипт для модели.

    Ходы нумеруются: номер попадает в audio_ref.turn при голосовом вводе, а
    сейчас просто помогает методисту найти место в истории.
    """
    lines = []
    for index, turn in enumerate(transcript):
        speaker = "СОТРУДНИК" if turn.role.value == "user" else "ПЕРСОНАЖ"
        lines.append(f"[{index}] {speaker}: {turn.text}")
    return "Транскрипт диалога:\n\n" + "\n".join(lines)


def build_report_schema(scenario: Scenario) -> dict:
    """JSON Schema отчёта под конкретную рубрику.

    Схема строится по сценарию, а не берётся статической: `criterion_id`
    ограничивается enum'ом реальных критериев, и модель не может изобрести
    несуществующий критерий или пропустить существующий.
    """
    criterion_ids = [item.id for item in scenario.rubric]

    return {
        "type": "object",
        "properties": {
            "verdict": {"type": "string"},
            "total_score": {"type": "number"},
            "scores": {
                "type": "array",
                "minItems": len(criterion_ids),
                "maxItems": len(criterion_ids),
                "items": {
                    "type": "object",
                    "properties": {
                        "criterion_id": {"type": "string", "enum": criterion_ids},
                        "score": {"type": "integer"},
                        "evidence": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Дословная цитата из реплики сотрудника",
                        },
                        "comment": {"type": "string"},
                    },
                    "required": ["criterion_id", "score", "evidence", "comment"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["verdict", "total_score", "scores"],
        "additionalProperties": False,
    }
