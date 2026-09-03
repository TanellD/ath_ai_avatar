"""Схема БД gateway — Claude.md §10: «сессии и отчёты в БД с первого дня».

Ходы диалога лежат отдельной таблицей, а не JSON-полем внутри сессии: отчёт
методиста ссылается на конкретный ход (§7, transcript и — в голосовой фазе —
audio_ref.turn), и такая ссылка должна быть настоящим ключом.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(String(128), index=True)
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

    session: Mapped[SessionRow] = relationship(back_populates="turns")

    __table_args__ = (Index("ix_turns_session_index", "session_id", "index", unique=True),)


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
