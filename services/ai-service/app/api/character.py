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

router = APIRouter(tags=["character"])
log = get_logger(__name__)


@router.post("/character/reply")
async def character_reply(payload: CharacterReplyRequest, request: Request):
    settings = get_settings()
    provider = request.app.state.llm

    system = build_character_system(payload.persona, payload.stage)
    messages = build_messages(payload.history, payload.summary, payload.user_text)

    async def event_stream() -> AsyncIterator[dict[str, str]]:
        parts: list[str] = []
        fallback = Emotion(payload.persona.mood.value)
        parser = EmotionPrefixParser(fallback)
        selected_emotion: Emotion | None = None

        async for token in provider.stream(
            system=system,
            messages=messages,
            model=settings.llm_fast_model,
            max_tokens=settings.character_max_tokens,
            temperature=settings.character_temperature,
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

        # `action` здесь всегда STAY: решение о переходе принимает автомат в
        # gateway по результату /classify, а не модель по своему усмотрению
        # (§5). Поле оставлено в контракте, чтобы протокол совпадал с §7.
        done = CharacterReplyDone(
            action=Action.STAY,
            full_text="".join(parts),
            emotion=selected_emotion or fallback,
        )
        yield {"event": "done", "data": done.model_dump_json()}

    return EventSourceResponse(event_stream())
