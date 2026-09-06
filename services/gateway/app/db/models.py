"""Схема БД gateway — Claude.md §10: «сессии и отчёты в БД с первого дня».

Ходы диалога лежат отдельной таблицей, а не JSON-полем внутри сессии: отчёт
методиста ссылается на конкретный ход (§7, transcript и — в голосовой фазе —
audio_ref.turn), и такая ссылка должна быть настоящим ключом.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def _utcnow() -> datetime:
    """Наивный UTC — как хранит остальная схема (DateTime без таймзоны) и как
    считает окна `admin_repository`. `datetime.utcnow()` дал бы то же самое,
    но он объявлен устаревшим."""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    """Владелец артефактов — не авторизация (Claude.md §4 её исключает).

    Пока ровно две строки, засеянные при старте (см. app/db/seed.py):
    один сотрудник (проходит тренировки) и один методист (владеет
    сценариями/отчётами). Когда понадобится больше одного из каждой роли —
    таблица уже на месте, добавлять нечего, только убрать засев фиксированных
    id и завести создание пользователей.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), doc="employee | methodist")
    display_name: Mapped[str] = mapped_column(String(128))


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(String(128), index=True)
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id"),
        index=True,
        doc="Кто проходит тренировку. Внутренняя деталь, не часть "
        "ath_contracts.SessionState (§7) — как и gen_id у TurnRow",
    )
    current_stage: Mapped[str] = mapped_column(String(128))
    current_gen: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)

    stage_history: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    turns: Mapped[list["TurnRow"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="TurnRow.index"
    )
    report: Mapped["ReportRow | None"] = relationship(
        back_populates="session", cascade="all, delete-orphan", uselist=False
    )


class TurnRow(Base):
    __tablename__ = "turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE")
    )
    index: Mapped[int] = mapped_column(Integer, doc="Порядковый номер хода в сессии")
    role: Mapped[str] = mapped_column(String(8))
    text: Mapped[str] = mapped_column(Text)
    stage_id: Mapped[str] = mapped_column(String(128))
    ts: Mapped[float] = mapped_column(Float, doc="Секунды от начала сессии")

    # [STT] Заполняются только при голосовом вводе; в текстовой фазе всегда NULL.
    # Колонки заведены сразу, чтобы включение голоса не требовало миграции
    # с переносом данных. См. docs/stt-phase.md.
    stt_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    audio_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Поколение, в рамках которого возник этот ход — «id сообщения» для
    # админ-панели: по нему группируются операции одного обмена репликами
    # (см. SpanRow). Не часть ath_contracts.Turn — внутренняя деталь этого
    # сервиса, наружу в §7-контрактах не нужна.
    gen_id: Mapped[int] = mapped_column(Integer, default=0, index=True)

    session: Mapped[SessionRow] = relationship(back_populates="turns")

    __table_args__ = (Index("ix_turns_session_index", "session_id", "index", unique=True),)


class SpanRow(Base):
    """Один шаг конвейера одного хода — данные для Gantt-визуализации в
    админ-панели (см. docs/architecture.md, «Наблюдаемость»).

    Не продуктовый контракт (§7) — внутренний инструмент отладки: «откуда
    ушло время на этот ответ». gen_id группирует спаны одного обмена
    репликами; start_ms/end_ms — относительно начала ЭТОГО хода (первый
    спан обычно начинается в районе 0), а не сессии целиком.
    """

    __tablename__ = "spans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    gen_id: Mapped[int] = mapped_column(Integer, index=True)
    seq: Mapped[int] = mapped_column(Integer, doc="Порядок операций внутри хода")
    operation: Mapped[str] = mapped_column(
        String(64), doc="character_reply | tts_synthesize | classify"
    )
    label: Mapped[str] = mapped_column(Text, doc="Что именно — текст предложения и т.п.")
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="ok", doc="ok | error | cancelled")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Настенное время записи спана — start_ms/end_ms относительны началу
    # хода и не годятся для графика активности во времени (дашборд
    # нагрузки, /admin/load). created_at даёт на это абсолютную ось.
    #
    # default (питоновский), а не только server_default: колонку добавляли в
    # уже существующую таблицу руками, а SQLite умеет в ALTER ... ADD COLUMN
    # только КОНСТАНТНЫЙ дефолт — в схеме осел литерал времени миграции, и
    # все спаны получали одну и ту же метку. Графики по времени из-за этого
    # были пусты всегда. server_default оставлен для свежесозданных БД.
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, server_default=func.now(), index=True
    )

    __table_args__ = (Index("ix_spans_session_gen", "session_id", "gen_id"),)


class ReportRow(Base):
    __tablename__ = "reports"

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    verdict: Mapped[str] = mapped_column(Text)
    total_score: Mapped[float] = mapped_column(Float)
    payload: Mapped[dict] = mapped_column(JSON, doc="Report целиком, как отдан клиенту")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    session: Mapped[SessionRow] = relationship(back_populates="report")
