"""_strip_inline_reasoning — вторая линия защиты от утечки chain-of-thought.

Живой баг: на сессии с локальной моделью reasoning_effort=none не сработал,
и модель написала рассуждение прямо в content как <thought>...</thought> —
оно ушло в субтитры и озвучилось сотруднику дословно (см. чат с пользователем
06.09.2026). Стриминговый разбор нужен потому, что открывающий/закрывающий
тег может располовиниться между двумя сетевыми чанками — построчная или
одноразовая regex-чистка всего текста здесь не годится, чанки приходят по
несколько символов.
"""

from collections.abc import AsyncIterator

import pytest

from app.llm.openai_compatible import _strip_inline_reasoning


async def _chunks(*parts: str) -> AsyncIterator[str]:
    for part in parts:
        yield part


async def _collect(parts: list[str]) -> str:
    return "".join([chunk async for chunk in _strip_inline_reasoning(_chunks(*parts))])


@pytest.mark.anyio
async def test_passthrough_without_any_tags() -> None:
    result = await _collect(["Прив", "ет, ", "как дела?"])
    assert result == "Привет, как дела?"


@pytest.mark.anyio
async def test_strips_thought_block_within_one_chunk() -> None:
    result = await _collect(["<thought>план ответа</thought>Реальный ответ."])
    assert result == "Реальный ответ."


@pytest.mark.anyio
async def test_strips_thought_block_split_across_many_chunks() -> None:
    """Ровно живой случай: тег и его содержимое размазаны по чанкам."""
    parts = ["<tho", "ught>", "долгие рас", "суждения про цену", "</though", "t>", "133 тысячи?"]
    result = await _collect(parts)
    assert result == "133 тысячи?"


@pytest.mark.anyio
async def test_strips_think_and_thinking_variants() -> None:
    assert await _collect(["<think>x</think>ответ1"]) == "ответ1"
    assert await _collect(["<thinking>x</thinking>ответ2"]) == "ответ2"
    assert await _collect(["<reasoning>x</reasoning>ответ3"]) == "ответ3"


@pytest.mark.anyio
async def test_tag_name_is_case_insensitive() -> None:
    result = await _collect(["<THOUGHT>x</THOUGHT>ответ"])
    assert result == "ответ"


@pytest.mark.anyio
async def test_text_before_and_after_tag_both_survive() -> None:
    result = await _collect(["До. ", "<thought>скрыто</thought>", " После."])
    assert result == "До.  После."


@pytest.mark.anyio
async def test_unrelated_angle_bracket_is_not_treated_as_reasoning_tag() -> None:
    """Модель играет продавца — вложенный тег с постороним именем не наш
    случай, но текст не должен потеряться."""
    result = await _collect(["Цена ", "<unknown>x</unknown>", " подтверждена"])
    assert result == "Цена <unknown>x</unknown> подтверждена"


@pytest.mark.anyio
async def test_unclosed_tag_discards_rest_of_stream() -> None:
    """Рассуждение без закрывающего тега (обрыв генерации) — честнее отдать
    пустую реплику, чем случайно проговорить середину рассуждения."""
    result = await _collect(["До текста. ", "<thought>обрыв без конца"])
    assert result == "До текста. "


@pytest.mark.anyio
async def test_multiple_thought_blocks_in_one_reply() -> None:
    result = await _collect(
        ["<thought>A</thought>Первая часть. ", "<thought>B</thought>Вторая часть."]
    )
    assert result == "Первая часть. Вторая часть."
