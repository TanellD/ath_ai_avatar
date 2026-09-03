"""Структурные логи speech-service.

Дубль gateway/app/core/logging.py. Вынести в packages/ — правильный шаг, но
только когда сервисов станет больше и файл начнёт расходиться; сейчас общий
пакет контрактов держит контракты, а не утилиты.
"""

import logging

import structlog

from app.core.config import get_settings

__all__ = ["get_logger", "setup_logging"]


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
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name or get_settings().service_name)
