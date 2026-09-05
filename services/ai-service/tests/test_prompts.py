"""Промпт персонажа: инициатива, открывающие реплики, возврат в русло.

Проверяется не формулировка (она будет меняться), а инварианты, на которых
держится тренажёр: критерий этапа не утекает персонажу, открывающая реплика
получает свой блок инструкций, а тон возврата в русло усиливается со вторым
подряд уходом от темы. См. docs/agent-initiative.md.
"""

from ath_contracts import Mood, OpeningKind, Persona, Stage

from app.character.prompts import build_character_system, build_messages

PERSONA = Persona(
    name="Ирина",
    role="закупщик среднего бизнеса",
    character="скептична, перебивает, торгуется",
    mood=Mood.NEUTRAL,
    difficulty=3,
    voice_id=None,
)

STAGE = Stage(
    id="opening",
    goal="Установить контакт и выяснить контекст",
    agent_opening="Здравствуйте. У меня десять минут, давайте по делу.",
    completion_criteria="Сотрудник представился и задал минимум один открытый вопрос",
    max_turns=4,
)


def test_completion_criteria_never_leaks_to_the_character() -> None:
    """Главный инвариант: чего персонаж не знает, того не проболтает."""
    for opening_kind in (None, OpeningKind.SESSION_START, OpeningKind.STAGE_TRANSITION):
        prompt = build_character_system(PERSONA, STAGE, opening_kind=opening_kind)
        assert STAGE.completion_criteria not in prompt


def test_character_is_told_not_to_write_stage_directions() -> None:
    """Живой прогон выдал «(разговор завершён)Ладно, слушаю…» — ремарку, которую
    TTS произнёс бы вслух. Правило про разметку это не покрывало."""
    prompt = build_character_system(PERSONA, STAGE)
    assert "ремарок в скобках" in prompt


def test_ordinary_reply_has_no_opening_block() -> None:
    prompt = build_character_system(PERSONA, STAGE)
    assert STAGE.agent_opening not in prompt
    assert "говоришь первым" not in prompt


def test_session_start_seeds_agent_opening_and_forbids_leading() -> None:
    prompt = build_character_system(PERSONA, STAGE, opening_kind=OpeningKind.SESSION_START)
    assert STAGE.agent_opening in prompt, "ориентир этапа должен попасть в промпт"
    assert "говоришь первым" in prompt
    # Перенос строки в шаблоне разрывает «и не / раскрывай», поэтому ищем хвост.
    assert "раскрывай критерий" in prompt


def test_session_start_leaves_self_introduction_to_the_role() -> None:
    """Представляться или нет — решает роль, а не шаблон.

    Раньше открывающая реплика начиналась с подставленного «меня зовут N,
    <роль>». Для кандидата на собеседовании это верно, а для закупщика,
    которому звонит продавец, — нет: первым представляется звонящий. Шаблон
    угадывал примерно в половине сценариев, поэтому убран, и промпт теперь
    прямо говорит решать по роли.
    """
    prompt = build_character_system(PERSONA, STAGE, opening_kind=OpeningKind.SESSION_START)

    assert "решай по роли" in prompt
    assert "меня зовут" not in prompt, "готового самопредставления в промпте быть не должно"


def test_stage_transition_tells_the_character_not_to_reintroduce() -> None:
    prompt = build_character_system(PERSONA, STAGE, opening_kind=OpeningKind.STAGE_TRANSITION)
    assert "заново не представляйся" in prompt
    assert STAGE.agent_opening in prompt


def test_silence_prompts_nudge_then_move_the_scene_forward() -> None:
    nudge = build_character_system(PERSONA, STAGE, opening_kind=OpeningKind.SILENCE_NUDGE)
    continuation = build_character_system(
        PERSONA, STAGE, opening_kind=OpeningKind.SILENCE_CONTINUE
    )

    assert "десять секунд" in nudge
    assert "мягко побуди" in nudge
    assert "новым" in continuation
    assert "этого же этапа" in continuation
    assert STAGE.completion_criteria not in nudge + continuation


def test_off_topic_nudge_escalates_then_stops() -> None:
    calm = build_character_system(PERSONA, STAGE, off_topic_streak=0)
    soft = build_character_system(PERSONA, STAGE, off_topic_streak=1)
    firm = build_character_system(PERSONA, STAGE, off_topic_streak=2)
    firmer = build_character_system(PERSONA, STAGE, off_topic_streak=7)

    assert "не по теме" not in calm
    assert "мягко" in soft
    assert "второй раз подряд" in firm
    # Потолок: дальше давить нечем, от застревания страхует max_turns в автомате.
    assert firmer == firm


def test_opening_block_wins_over_off_topic_nudge() -> None:
    """У открывающей реплики нет предыдущей реплики пользователя, возвращать
    в русло нечего — даже если стрик остался с прошлого этапа."""
    prompt = build_character_system(
        PERSONA, STAGE, opening_kind=OpeningKind.SESSION_START, off_topic_streak=2
    )
    assert "второй раз подряд" not in prompt
    assert "говоришь первым" in prompt


def test_messages_start_with_user_role_on_empty_history() -> None:
    """Anthropic отклоняет пустой список и список не с роли user — открывающая
    реплика обязана это пережить (docs/agent-initiative.md)."""
    messages = build_messages([], "", "[Ты говоришь первым.]")

    assert messages, "пустой список сообщений API не примет"
    assert messages[0]["role"] == "user"
    assert messages[-1]["role"] == "user"
