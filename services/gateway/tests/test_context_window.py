"""evicted_since — граница между «ещё видно модели», «уже свёрнуто в
summary» и «выпало без следа» (§5).

Регресс к жалобе «теряется контекст, когда сообщений становится больше»:
build_context раньше просто отрезал всё за пределами окна, а summary
никогда не заполнялся (TODO в старом summarize_evicted). evicted_since —
чистая функция, считающая, что именно нужно досдать суммаризации на этом
ходу, не задевая сеть."""

from ath_contracts import Turn, TurnRole

from app.orchestrator.context_window import build_context, evicted_since


def _turn(text: str) -> Turn:
    return Turn(role=TurnRole.USER, text=text, stage_id="opening", ts=0.0)


def test_evicted_since_empty_while_turns_fit_the_window() -> None:
    turns = [_turn(str(i)) for i in range(6)]
    assert evicted_since(turns, max_turns=6, summarized_through=0) == []


def test_evicted_since_returns_only_newly_pushed_out_turns() -> None:
    turns = [_turn(str(i)) for i in range(8)]
    # Окно — 6, значит вытеснено 2 первых хода; ни один из них ещё не
    # сворачивался (summarized_through=0).
    evicted = evicted_since(turns, max_turns=6, summarized_through=0)
    assert [t.text for t in evicted] == ["0", "1"]


def test_evicted_since_does_not_repeat_already_summarized_turns() -> None:
    turns = [_turn(str(i)) for i in range(9)]
    # Первый ход уже свёрнут раньше — досдаём только второй и третий
    # (вытеснено уже 3 из 9 при окне 6).
    evicted = evicted_since(turns, max_turns=6, summarized_through=1)
    assert [t.text for t in evicted] == ["1", "2"]


def test_evicted_since_never_reaches_into_the_visible_window() -> None:
    """summarized_through не может обогнать границу вытеснения — иначе
    суммаризация утащила бы в выжимку ход, который модель ещё видит целиком."""
    turns = [_turn(str(i)) for i in range(6)]
    assert evicted_since(turns, max_turns=6, summarized_through=0) == []


def test_build_context_still_only_slices_the_recent_window() -> None:
    """evicted_since — новая функция рядом, build_context не меняла поведение."""
    turns = [_turn(str(i)) for i in range(8)]
    context = build_context(turns, max_turns=6, summary="выжимка")
    assert [t.text for t in context.recent] == ["2", "3", "4", "5", "6", "7"]
    assert context.summary == "выжимка"
