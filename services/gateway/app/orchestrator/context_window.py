"""Скользящее окно контекста — Claude.md §5.

Полный текст последних N ходов + сжатая выжимка остального. Без окна стоимость
диалога растёт квадратично: каждый ход тащит за собой всю историю.
"""

from dataclasses import dataclass

from ath_contracts import Turn


@dataclass
class ContextWindow:
    """Что уходит в ai-service на каждый ход."""

    recent: list[Turn]
    summary: str


def build_context(turns: list[Turn], max_turns: int, summary: str = "") -> ContextWindow:
    """Собрать окно из полной истории ходов.

    Вытесненные ходы не выбрасываются из сессии — они остаются в БД и целиком
    попадают в отчёт методисту (§7, transcript). Окно сужает только то, что
    видит модель.
    """
    if len(turns) <= max_turns:
        return ContextWindow(recent=list(turns), summary=summary)

    return ContextWindow(recent=turns[-max_turns:], summary=summary)


async def summarize_evicted(evicted: list[Turn], previous_summary: str) -> str:
    """Обновить выжимку вытесненными ходами.

    TODO: вызов быстрой модели через ai-service. Сжимать инкрементально
    (предыдущая выжимка + новые вытесненные ходы), а не пересобирать по всей
    истории — иначе экономия окна съедается стоимостью суммаризации.

    До реализации возвращаем предыдущую выжимку без изменений: на сценарии из
    четырёх этапов история почти никогда не выходит за окно, так что заглушка
    здесь ничего не ломает.
    """
    return previous_summary
