"""Сценарий тренировки — Claude.md §7.

Создаётся методистом: из шаблона, из сгенерированного черновика или с нуля.

Часть текста сценария — с подстановками: методист пишет скелет («Вы продаёте
{product} компании {company}»), объявляет слоты, а конкретные значения модель
подбирает под каждый прогон. Зачем так, а не «весь текст статичный» и не «весь
текст генерируется заново»:

  - статичный текст противоречит §7, где `mood` и `difficulty` специально
    варьируются между прогонами — «ответ на главную жалобу пользователей
    аналогов (предсказуемость бота)». Один и тот же «Северный Ветер» на пятом
    прогоне работает против той же цели;
  - генерация текста целиком стоит абзаца токенов на каждое открытие и отдаёт
    модели формулировки методиста. Список из пяти коротких значений — полсотни
    токенов, и схема ответа строится из объявленных слотов, поэтому лишнего
    ключа или пропущенного в нём быть не может.

Подстановка идёт по ВСЕМУ сценарию, а не только по тексту брифа. Иначе
сотрудник прочтёт про «Северный Ветер», скажет это персонажу — а персонаж,
собранный из неподставленной персоны, о такой компании не слышал.
"""

import re
from collections.abc import Mapping

from pydantic import BaseModel, Field

from ath_contracts.enums import Mood


class Persona(BaseModel):
    """Персонаж, с которым разговаривает сотрудник."""

    name: str
    role: str
    character: str = Field(description="Манера: скептична, перебивает, торгуется")
    mood: Mood = Mood.NEUTRAL
    difficulty: int = Field(default=1, ge=1, le=5)
    voice_id: str | None = None
    holds_initiative: bool = Field(
        default=True,
        description=(
            "Держит ли персонаж инициативу разговора (Claude.md §1) — спрашивает, "
            "уточняет, дожимает. По умолчанию True: в большинстве сценариев "
            "(продажи, возражения) агент ведёт разговор, а сотрудник отвечает — "
            "ровно то, что описывает §1. Но не универсально: на собеседовании "
            "инициативу держит СОТРУДНИК (он интервьюер), а персонаж — кандидат, "
            "который отвечает на вопросы и не должен сам вести допрос. Без этого "
            "поля системный промпт одинаково учил бы любого персонажа "
            "перехватывать инициативу, и кандидат начинал бы собеседовать "
            "интервьюера — реальный баг, найденный на interview_junior."
        ),
    )


class Stage(BaseModel):
    """Этап сценария. Переход между этапами делает код, не модель (§5)."""

    id: str
    goal: str
    agent_opening: str = Field(description="Чем персонаж открывает этап")
    completion_criteria: str = Field(
        description="Формулировка для классификатора: когда этап считается пройденным"
    )
    max_turns: int = Field(default=4, ge=1, description="Страховка от зацикливания")


class RubricItem(BaseModel):
    """Критерий оценки. Под каждый критерий отчёт обязан дать цитату (§7)."""

    id: str
    name: str
    description: str
    scale: int = Field(default=5, ge=2)
    weight: float = Field(default=1.0, gt=0)


class ScenarioSlot(BaseModel):
    """Деталь, которую модель подбирает заново под каждый прогон."""

    id: str = Field(description="Ключ подстановки: {company}")
    label: str = Field(description="Подпись поля в редакторе")
    hint: str = Field(description="Что именно придумать: «название компании-закупщика»")
    example: str = Field(
        description="Значение по умолчанию. Показывается методисту на превью и "
        "подставляется, если подобрать детали не удалось"
    )


class Scenario(BaseModel):
    id: str
    title: str
    persona: Persona
    stages: list[Stage] = Field(min_length=1)
    rubric: list[RubricItem] = Field(min_length=1)
    tags: list[str] = Field(default_factory=list, description="Для поиска и фильтрации у методиста")

    briefing: str = Field(
        default="",
        description="Что сотрудник читает перед разговором: обстановка, кто перед ним "
        "и чего он хочет. Может содержать подстановки {slot_id}",
    )
    slots: list[ScenarioSlot] = Field(default_factory=list)


_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def render_text(text: str, values: Mapping[str, str]) -> str:
    """Подставить значения слотов.

    Намеренно НЕ `str.format_map`: у методиста в тексте может оказаться одинокая
    фигурная скобка, и формат уронил бы на ней весь сценарий. Неизвестный
    плейсхолдер остаётся как есть — это видно глазами и не мешает разговору.
    """
    return _PLACEHOLDER.sub(lambda match: values.get(match.group(1), match.group(0)), text)


def slot_defaults(scenario: Scenario) -> dict[str, str]:
    return {slot.id: slot.example for slot in scenario.slots}


def render_scenario(scenario: Scenario, values: Mapping[str, str]) -> Scenario:
    """Сценарий этого прогона.

    Идентификаторы не трогаем никогда: по ним ходит автомат этапов, покрытие
    рубрики в отчёте и ссылки. Меняется только то, что читают люди и модель.
    """
    if not values:
        return scenario

    def render(text: str) -> str:
        return render_text(text, values)

    return scenario.model_copy(
        update={
            "title": render(scenario.title),
            "briefing": render(scenario.briefing),
            "persona": scenario.persona.model_copy(
                update={
                    "name": render(scenario.persona.name),
                    "role": render(scenario.persona.role),
                    "character": render(scenario.persona.character),
                }
            ),
            "stages": [
                stage.model_copy(
                    update={
                        "goal": render(stage.goal),
                        "agent_opening": render(stage.agent_opening),
                        "completion_criteria": render(stage.completion_criteria),
                    }
                )
                for stage in scenario.stages
            ],
            "rubric": [
                item.model_copy(
                    update={"name": render(item.name), "description": render(item.description)}
                )
                for item in scenario.rubric
            ],
        }
    )
