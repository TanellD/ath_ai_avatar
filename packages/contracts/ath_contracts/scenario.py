"""Сценарий тренировки — Claude.md §7.

Создаётся методистом: из шаблона, из сгенерированного черновика или с нуля.
"""

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


class Scenario(BaseModel):
    id: str
    title: str
    persona: Persona
    stages: list[Stage] = Field(min_length=1)
    rubric: list[RubricItem] = Field(min_length=1)
