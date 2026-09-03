"""Запись операционных спанов одного хода — данные для Gantt-визуализации.

Внутренний инструмент отладки/наблюдаемости, не продуктовый контракт (§7):
«откуда ушло время на этот конкретный ответ». Один SpanRecorder — на один
вызов `_run_turn`, живёт ровно столько же.

Пишет в БД сразу по завершении каждой операции, а не батчем в конце: если ход
отменят на середине (barge-in, §6) или упадёт с ошибкой (см. историю с
router.cheap, молча игнорирующим output_config), спан всё равно попадёт в
таблицу — это и есть тот случай, когда наблюдаемость нужнее всего.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.logging import get_logger
from app.db.engine import session_factory
from app.db.models import SpanRow

log = get_logger(__name__)


class SpanRecorder:
    def __init__(self, session_id: str, gen_id: int) -> None:
        self._session_id = session_id
        self._gen_id = gen_id
        self._turn_started_at = time.monotonic()
        self._seq = 0

    @asynccontextmanager
    async def span(self, operation: str, label: str) -> AsyncIterator[None]:
        """Обернуть одну операцию хода (вызов LLM, TTS-синтез предложения,
        классификацию). start_ms/end_ms — относительно начала ЭТОГО хода."""
        seq = self._seq
        self._seq += 1
        start_ms = self._elapsed_ms()
        status = "ok"
        error: str | None = None
        try:
            yield
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except Exception as exc:
            status = "error"
            error = str(exc)[:500]
            raise
        finally:
            end_ms = self._elapsed_ms()
            await self._persist(seq, operation, label, start_ms, end_ms, status, error)

    def _elapsed_ms(self) -> int:
        return round((time.monotonic() - self._turn_started_at) * 1000)

    async def _persist(
        self,
        seq: int,
        operation: str,
        label: str,
        start_ms: int,
        end_ms: int,
        status: str,
        error: str | None,
    ) -> None:
        try:
            async with session_factory()() as db:
                db.add(
                    SpanRow(
                        session_id=self._session_id,
                        gen_id=self._gen_id,
                        seq=seq,
                        operation=operation,
                        label=label[:2000],
                        start_ms=start_ms,
                        end_ms=end_ms,
                        status=status,
                        error=error,
                    )
                )
                await db.commit()
        except Exception:
            # Наблюдаемость не имеет права уронить сам ход — если запись
            # спана не удалась, теряем один ряд в админ-панели, а не ответ
            # персонажа сотруднику.
            log.exception(
                "tracing.span_persist_failed",
                session_id=self._session_id,
                gen_id=self._gen_id,
                operation=operation,
            )
