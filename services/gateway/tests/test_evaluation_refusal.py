"""Отказ в оценке: когда повторять бессмысленно, так и надо сказать.

Живой случай: сотрудник открыл тренировку и закрыл, не сказав ни слова.
Персонаж успел поздороваться — то есть ход в сессии есть, и прежняя проверка
«есть хоть что-то» её пропускала. Дальше оценка неизбежно разваливалась: под
каждым баллом обязана стоять дословная цитата сотрудника (§7), а цитировать
нечего. Модель честно отвечала «[реплики сотрудника отсутствуют]»,
report_builder так же честно отбраковывал отчёт 422-м, а gateway переводил
это в 504 «попробуйте ещё раз» — и методист жал кнопку сколько угодно.
"""

import httpx
import pytest
from ath_contracts import Mood, Persona, RubricItem, Scenario, Stage, Turn, TurnRole

from app.clients.ai_client import AiClient, EvaluationRejected, EvaluationUnavailable

SCENARIO = Scenario(
    id="objection_price",
    title="Возражение «дорого»",
    persona=Persona(name="Ирина", role="закупщик", character="скептична", mood=Mood.NEUTRAL),
    stages=[
        Stage(
            id="opening",
            goal="Контакт",
            agent_opening="Слушаю.",
            completion_criteria="Представился",
        )
    ],
    rubric=[RubricItem(id="discovery", name="Выявление", description="Открытые вопросы")],
)


def client_over(handler) -> AiClient:  # noqa: ANN001
    client = AiClient(base_url="http://ai", timeout=5.0)
    client._client = httpx.AsyncClient(base_url="http://ai", transport=httpx.MockTransport(handler))
    return client


async def evaluate(client: AiClient) -> None:
    await client.evaluate(
        session_id="s1",
        scenario=SCENARIO,
        transcript=[],
        duration_sec=10,
        stages_completed=0,
        stages_total=1,
    )


async def test_rejected_report_is_not_reported_as_a_timeout() -> None:
    """422 из report_builder — окончательный отказ, а не заминка связи."""
    reason = "критерий discovery: цитата отсутствует в репликах сотрудника"

    def rejected(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": reason})

    with pytest.raises(EvaluationRejected) as caught:
        await evaluate(client_over(rejected))

    # Причина доходит наружу дословно: она про конкретный разговор и методисту
    # понятнее любого общего текста.
    assert reason in str(caught.value)


async def test_provider_silence_stays_a_timeout() -> None:
    """А вот это как раз лечится повтором, и путь должен остаться прежним."""

    def unavailable(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(504, text="upstream timeout")

    with pytest.raises(EvaluationUnavailable):
        await evaluate(client_over(unavailable))


async def test_rejection_is_not_swallowed_by_the_timeout_branch() -> None:
    """EvaluationRejected не наследует httpx.HTTPError — иначе except ниже
    поймал бы его и снова превратил в «попробуйте ещё раз»."""
    assert not issubclass(EvaluationRejected, httpx.HTTPError)
    assert not issubclass(EvaluationRejected, EvaluationUnavailable)


def test_session_with_only_agent_turns_has_nothing_to_quote() -> None:
    """Ровно то состояние, на котором ломалась оценка: ход есть, а
    процитировать нечего. Проверка в rebuild_report смотрит на роль, а не на
    длину списка."""
    turns = [Turn(role=TurnRole.AGENT, text="Слушаю.", stage_id="opening", ts=0)]

    assert turns, "ход в сессии есть — прежняя проверка «не пусто» её пропускала"
    assert not any(turn.role is TurnRole.USER for turn in turns)
