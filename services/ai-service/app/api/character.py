"""Реплика персонажа потоком — Claude.md §5.

SSE, а не обычный ответ: gateway должен получить первый токен как можно раньше,
чтобы отправить первое предложение в TTS, не дожидаясь конца генерации.
Синхронный ответ здесь ломает метрику 1 напрямую.

События потока:
    event: token   data: {"text": "..."}
    event: done    data: {"action": "stay", "full_text": "..."}
"""

import json
from collections.abc import AsyncIterator

from ath_contracts import Action, Emotion
from ath_contracts.api import CharacterReplyDone, CharacterReplyMeta, CharacterReplyRequest
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app.character.emotion_parser import EmotionPrefixParser
from app.character.prompts import build_character_system, build_messages
from app.core.config import get_settings
from app.core.logging import get_logger
from app.llm.base import LlmProvider

router = APIRouter(tags=["character"])
log = get_logger(__name__)


async def stream_character_reply(
    provider: LlmProvider,
    system: str,
    messages: list[dict[str, str]],
    model: str,
    max_tokens: int,
    temperature: float,
    fallback: Emotion,
) -> AsyncIterator[dict[str, str]]:
    """SSE-события одной реплики персонажа. Вынесено из роута, чтобы
    юнит-тестировать без HTTP/ASGI — роуту достаточно подставить провайдер.
    """
    parts: list[str] = []
    parser = EmotionPrefixParser(fallback)
    selected_emotion: Emotion | None = None

    # Открывающую реплику целиком пишет модель. Раньше сюда первым токеном
    # подставлялось готовое самопредставление («меня зовут N, <роль>») —
    # оно снимало вызов LLM с критического пути до первого звука, но
    # угадывало роль лишь в половине сценариев: закупщик, которому звонит
    # продавец, представляется первым только в плохом тренажёре. Роль
    # важнее задержки, поэтому шаблон убран; кто здоровается и как —
    # решает промпт (_OPENING_SESSION_START).
    async for token in provider.stream(
        system=system,
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    ):
        parsed = parser.feed(token)
        if parsed.emotion is not None:
            selected_emotion = parsed.emotion
            meta = CharacterReplyMeta(emotion=selected_emotion)
            yield {"event": "meta", "data": meta.model_dump_json()}
        if parsed.text:
            parts.append(parsed.text)
            yield {
                "event": "token",
                "data": json.dumps({"text": parsed.text}, ensure_ascii=False),
            }

    tail = parser.finish()
    if tail.emotion is not None:
        selected_emotion = tail.emotion
        meta = CharacterReplyMeta(emotion=selected_emotion)
        yield {"event": "meta", "data": meta.model_dump_json()}
    if tail.text:
        parts.append(tail.text)
        yield {"event": "token", "data": json.dumps({"text": tail.text}, ensure_ascii=False)}

    full_text = "".join(parts)
    if not full_text:
        # Живой баг на локальной думающей модели: рассуждение съедало весь
        # max_tokens (finish_reason "length"), content приходил пустым, и
        # персонаж молча не отвечал — ни строчки в логе, сотрудник слышит
        # тишину. reasoning_effort=none и _strip_inline_reasoning (см.
        # openai_compatible.py) закрывают известные причины, но не все
        # провайдеры их уважают — если реплика всё равно вышла пустой, это
        # стоит увидеть в логах сразу, а не реконструировать по жалобе
        # сотрудника четыре часа спустя.
        log.warning("character.empty_reply", model=model, max_tokens=max_tokens)

    # `action` здесь всегда STAY: решение о переходе принимает автомат в
    # gateway по результату /classify, а не модель по своему усмотрению
    # (§5). Поле оставлено в контракте, чтобы протокол совпадал с §7.
    done = CharacterReplyDone(
        action=Action.STAY,
        full_text=full_text,
        emotion=selected_emotion or fallback,
    )
    yield {"event": "done", "data": done.model_dump_json()}


@router.post("/character/reply")
async def character_reply(payload: CharacterReplyRequest, request: Request):
    settings = get_settings()
    provider = request.app.state.llm

    system = build_character_system(
        payload.persona,
        payload.stage,
        opening_kind=payload.opening_kind,
        off_topic_streak=payload.off_topic_streak,
    )
    messages = build_messages(payload.history, payload.summary, payload.user_text)

    return EventSourceResponse(
        stream_character_reply(
            provider=provider,
            system=system,
            messages=messages,
            model=settings.llm_fast_model,
            max_tokens=settings.character_max_tokens,
            temperature=settings.character_temperature,
            fallback=Emotion(payload.persona.mood.value),
        )
    )
