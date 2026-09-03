"""Схема БД сценариев.

Сценарий хранится одним JSON-документом, а не разложенным по таблицам
persona/stages/rubric. Причина: сценарий всегда читается и пишется целиком, а
его форма (§7) ещё будет меняться по ходу проекта. Нормализация здесь дала бы
миграцию на каждое поле персонажа и ничего не дала бы взамен — запросов «найти
все сценарии, где difficulty > 3» в постановке нет.

Ключевые поля вынесены отдельными колонками, чтобы список сценариев у методиста
собирался без разбора JSON.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


class ScenarioRow(Base):
    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    persona_name: Mapped[str] = mapped_column(String(128))
    stages_count: Mapped[int] = mapped_column(Integer, default=0)
    rubric_count: Mapped[int] = mapped_column(Integer, default=0)

    is_template: Mapped[bool] = mapped_column(
        Boolean, default=False, doc="Встроенный шаблон: методист копирует его, а не правит"
    )

    payload: Mapped[dict] = mapped_column(JSON, doc="Scenario целиком, по контракту §7")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
