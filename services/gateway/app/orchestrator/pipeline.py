"""Ход диалога: user_message → LLM → сплиттер → TTS → клиент.

Claude.md §5. Соответствие схеме из постановки:

    user text
      → orchestrator (состояние сценария, gen_id)   ← session_manager + fsm
        → LLM stream (реплика персонажа + action)   ← clients/ai_client
          → sentence splitter                        ← sentence_splitter
            → TTS stream (чанки аудио)               ← clients/speech_client
              → client: audio playback = единственные часы

Ключевое правило файла: **каждое исходящее событие проходит через
`_send()`, который сверяет gen_id.** Прямых вызовов `websocket.send_json`
в обход него быть не должно — это и есть метрика 4.
"""

import asyncio
import base64
import io
import wave
from collections.abc import Awaitable, Callable, Coroutine

from ath_contracts import (
    ActionEvent,
    AudioChunkEvent,
    CancelEvent,
    Classification,
    Emotion,
    ServerEvent,
    SubtitleEvent,
    TokenEvent,
    Turn,
    TurnRole,
)
from ath_contracts.api import CharacterReplyMeta

from app.clients.ai_client import AiClient
from app.clients.speech_client import SpeechClient
from app.core.logging import get_logger
from app.db.engine import session_factory
from app.db.repositories import SqlSessionRepository
from app.orchestrator.avatar_voice import voice_for
from app.orchestrator.context_window import build_context
from app.orchestrator.sentence_splitter import SentenceSplitter
from app.orchestrator.session_manager import LiveSession
from app.tracing import SpanRecorder

log = get_logger(__name__)

SendFn = Callable[[ServerEvent], Awaitable[None]]
"""Отправка события в сокет. Передаётся снаружи, чтобы pipeline не знал про FastAPI."""

def wav_duration_ms(data_b64: str) -> int:
    """Длительность WAV-чанка в миллисекундах — из заголовка, не из длины текста.

    Источник тайминга для субтитров (§7: «start_ms, end_ms — тайминги
    относительно начала аудио поколения»). Считать по числу символов текста
    было бы оценкой на глаз — реальная длительность зависит от темпа речи
    конкретного голоса, а не только от длины строки. Каждый чанк — валидный
    самостоятельный WAV (см. speech-service/app/tts/mock.py,
    soniox.py:_pcm_to_wav) — заголовок читается напрямую, без декодирования
    сэмплов.
    """
    raw = base64.b64decode(data_b64)
    with wave.open(io.BytesIO(raw), "rb") as wav_file:
        rate = wav_file.getframerate()
        if not rate:
            return 0
        return round(1000 * wav_file.getnframes() / rate)


class TurnPipeline:
    def __init__(
        self,
        session: LiveSession,
        ai: AiClient,
        speech: SpeechClient,
        send: SendFn,
        max_context_turns: int,
    ) -> None:
        self._session = session
        self._ai = ai
        self._speech = speech
        self._raw_send = send
        self._max_context_turns = max_context_turns
        # Держит ссылки на fire-and-forget задачи (запись хода в БД), пока
        # они не завершатся — иначе их может собрать GC на середине, это
        # известная ловушка asyncio.create_task без сохранённой ссылки.
        self._background_tasks: set[asyncio.Task[None]] = set()

    def _fire_and_forget(self, coro: Coroutine[object, object, None]) -> None:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    # ------------------------------------------------------------------ API

    async def handle_user_message(
        self, text: str, interrupts: int | None, avatar_id: str = "avatar-aith"
    ) -> None:
        """Точка входа хода. Реализует §6, шаги 3-5.

        Шаги 1-2 (локальная остановка звука и отправка события) — на клиенте,
        и намеренно: они обязаны укладываться в 300 мс без сетевого
        round-trip. Здесь начинается серверная половина протокола.
        """
        gen_id = await self.begin_user_turn(interrupts)

        user_turn = self._session.add_turn(TurnRole.USER, text)
        # Не await: запись в БД не должна задерживать обработку следующего
        # события в цикле приёма — от этого зависит бюджет barge-in (§9).
        self._fire_and_forget(self._persist_turn(user_turn, gen_id))

        self._start_pipeline(gen_id, text, avatar_id)

    async def begin_user_turn(self, interrupts: int | None) -> int:
        """Один authoritative bump для text или PTT начала."""
        generations = self._session.generations
        gen_id = generations.bump()
        if interrupts is not None:
            await generations.cancel(interrupts)
            await self._raw_send(CancelEvent(gen_id=interrupts))
        return gen_id

    async def handle_voice_final(
        self,
        *,
        gen_id: int,
        capture_id: str,
        text: str,
        confidence: float | None,
    ) -> bool:
        """Commit final transcript once, then reuse the normal dialogue pipeline."""
        if self._session.generations.is_stale(gen_id) or not text.strip():
            return False
        turn = self._session.make_turn(
            TurnRole.USER, text.strip(), stt_confidence=confidence
        )
        index = len(self._session.turns)
        async with session_factory()() as db:
            inserted = await SqlSessionRepository(db).commit_voice_turn(
                self._session.session_id, capture_id, index, turn, gen_id
            )
        if not inserted:
            return False
        self._session.accept_turn(turn)
        # Голосовой ход берёт аватар из сессии: выбор приезжает на speech_start,
        # а не на user_message, но голос обязан быть тем же самым.
        self._start_pipeline(gen_id, turn.text, self._session.avatar_id)
        return True

    def _start_pipeline(self, gen_id: int, text: str, avatar_id: str) -> None:
        task = asyncio.create_task(self._run_turn(gen_id, text, avatar_id))
        self._session.generations.register(gen_id, task)

    # -------------------------------------------------------------- внутри

    async def _run_turn(self, gen_id: int, user_text: str, avatar_id: str) -> None:
        """Один ход целиком. Отменяется целиком по task.cancel()."""
        recorder = SpanRecorder(self._session.session_id, gen_id)
        try:
            await self._speak(gen_id, user_text, avatar_id, recorder)
            await self._advance_stage(gen_id, user_text, recorder)
        except asyncio.CancelledError:
            log.info("pipeline.turn_cancelled", gen_id=gen_id)
            raise
        except Exception:
            log.exception("pipeline.turn_failed", gen_id=gen_id)
            raise

    async def _persist_turn(self, turn: Turn, gen_id: int) -> None:
        """Пишет ход в БД сразу, а не только на disconnect — админ-панель и
        отчёт читают из БД, а не из памяти процесса."""
        index = len(self._session.turns) - 1
        try:
            async with session_factory()() as db:
                await SqlSessionRepository(db).append_turn(
                    self._session.session_id, index, turn, gen_id
                )
        except Exception:
            log.exception("pipeline.persist_turn_failed", gen_id=gen_id)

    async def _speak(
        self, gen_id: int, user_text: str, avatar_id: str, recorder: SpanRecorder
    ) -> None:
        """Реплика персонажа: токены LLM → предложения → чанки TTS.

        TODO: обвязка готова, тела клиентов — заглушки. Что здесь должно
        появиться при подключении реальных провайдеров:
          - параллельный запуск TTS для предложения N и продолжение чтения
            токенов N+1 (сейчас последовательно, и это съедает time to first
            audio на длинных ответах).
        """
        stage = self._session.machine.stage(self._session.current_stage_id)
        context = build_context(
            self._session.turns, self._max_context_turns, self._session.summary
        )

        splitter = SentenceSplitter()
        full_text: list[str] = []
        emotion = Emotion(self._session.scenario.persona.mood.value)
        voice_id = voice_for(avatar_id, self._session.scenario.persona)
        seq = 0
        elapsed_ms = 0
        """Сколько аудио этого поколения уже отправлено — начало отсчёта для
        следующего SubtitleEvent. Тайминги относительно начала поколения (§7),
        не абсолютное время."""

        persona_name = self._session.scenario.persona.name
        async with recorder.span(
            "character_reply", f'{persona_name}: ответ на "{user_text[:60]}"'
        ):
            async for item in self._ai.stream_character_reply(
                persona=self._session.scenario.persona,
                stage=stage,
                history=context.recent,
                summary=context.summary,
                user_text=user_text,
            ):
                if isinstance(item, CharacterReplyMeta):
                    emotion = item.emotion
                    continue

                token = item
                full_text.append(token)
                await self._send(gen_id, TokenEvent(gen_id=gen_id, text=token))

                for sentence in splitter.feed(token):
                    seq, elapsed_ms = await self._synthesize(
                        gen_id, sentence, seq, elapsed_ms, emotion, voice_id, recorder
                    )

            tail = splitter.flush()
            if tail:
                seq, elapsed_ms = await self._synthesize(
                    gen_id, tail, seq, elapsed_ms, emotion, voice_id, recorder
                )

        agent_turn = self._session.add_turn(TurnRole.AGENT, "".join(full_text))
        await self._persist_turn(agent_turn, gen_id)

    async def _synthesize(
        self,
        gen_id: int,
        sentence: str,
        seq: int,
        elapsed_ms: int,
        emotion: Emotion,
        voice_id: str | None,
        recorder: SpanRecorder,
    ) -> tuple[int, int]:
        """Озвучить одно предложение, отдавая чанки по мере готовности (§10).

        Заодно копит длительность и шлёт SubtitleEvent по завершении
        предложения — клиент использует его, чтобы показывать текст в такт
        голосу, а не в такт токенам (токены приходят быстрее речи).
        """
        sentence_ms = 0
        async with recorder.span("tts_synthesize", sentence):
            async for chunk in self._speech.stream_tts(
                gen_id=gen_id,
                seq=seq,
                text=sentence,
                voice_id=voice_id,
                emotion=emotion,
            ):
                await self._send(
                    gen_id,
                    AudioChunkEvent(
                        gen_id=gen_id,
                        seq=chunk.seq,
                        data=chunk.data,
                        format=chunk.format,
                        emotion=emotion,
                    ),
                )
                sentence_ms += wav_duration_ms(chunk.data)
                seq = chunk.seq + 1

        await self._send(
            gen_id,
            SubtitleEvent(
                gen_id=gen_id,
                text=sentence,
                start_ms=elapsed_ms,
                end_ms=elapsed_ms + sentence_ms,
            ),
        )
        return seq, elapsed_ms + sentence_ms

    async def _advance_stage(self, gen_id: int, user_text: str, recorder: SpanRecorder) -> None:
        """Классификация ответа моделью, решение о переходе — кодом (§5)."""
        stage = self._session.machine.stage(self._session.current_stage_id)
        context = build_context(
            self._session.turns, self._max_context_turns, self._session.summary
        )

        async with recorder.span("classify", f'Критерий этапа "{stage.id}"'):
            classification: Classification = await self._ai.classify(
                stage=stage, history=context.recent, user_text=user_text
            )

        transition = self._session.machine.decide(
            current_stage_id=self._session.current_stage_id,
            classification=classification,
            turns_spent=self._session.turns_in_stage,
        )

        if transition.exit_reason is not None:
            self._session.leave_stage(transition.exit_reason, transition.next_stage_id)

        await self._send(
            gen_id,
            ActionEvent(
                gen_id=gen_id,
                action=transition.action,
                stage_id=self._session.current_stage_id,
            ),
        )

    async def _send(self, gen_id: int, event: ServerEvent) -> None:
        """Отправка с проверкой поколения.

        Единственный разрешённый путь наружу для событий, привязанных к
        поколению. Если поколение устарело — событие молча гасится: это и
        есть «ни один чанк старого поколения не воспроизводится» (§6).
        """
        if self._session.generations.is_stale(gen_id):
            log.debug("pipeline.dropped_stale", gen_id=gen_id, event=event.type)
            return
        await self._raw_send(event)
