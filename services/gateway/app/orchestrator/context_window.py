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


def evicted_since(turns: list[Turn], max_turns: int, summarized_through: int) -> list[Turn]:
    """Ходы, которые уже выпали из окна (`build_context` их не отдаст), но ещё
    не попали в выжимку — то, что нужно доотдать суммаризации на этом ходу.

    Чистая функция без обращения к модели намеренно: вызывающий (pipeline.py)
    решает, стоит ли платить вызовом ai-service за пустой или маленький
    результат, — эта функция только считает границы среза.
    """
    evicted_count = max(len(turns) - max_turns, 0)
    if evicted_count <= summarized_through:
        return []
    return turns[summarized_through:evicted_count]
