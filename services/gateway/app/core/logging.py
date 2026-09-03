"""Структурные логи.

`session_id` и `gen_id` привязываются к контексту в начале обработки события и
дальше попадают в каждую строку автоматически. Без этого разбор «почему хвост
отменённого поколения всё-таки прозвучал» превращается в археологию.
"""

import logging

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.core.config import get_settings

__all__ = ["bind_session_context", "clear_session_context", "get_logger", "setup_logging"]


def setup_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_format == "json"
        else structlog.dev.ConsoleRenderer()
    )

    logging.basicConfig(format="%(message)s", level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name or get_settings().service_name)


def bind_session_context(session_id: str, gen_id: int | None = None) -> None:
    """Привязать сессию (и поколение) ко всем последующим строкам лога."""
    bind_contextvars(session_id=session_id)
    if gen_id is not None:
        bind_contextvars(gen_id=gen_id)


def clear_session_context() -> None:
    clear_contextvars()
