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
from collections.abc import Awaitable, Callable

from ath_contracts import (
    ActionEvent,
    AudioChunkEvent,
    CancelEvent,
    Classification,
    ServerEvent,
    SubtitleEvent,
    TokenEvent,
    TurnRole,
)

from app.clients.ai_client import AiClient
from app.clients.speech_client import SpeechClient
from app.core.logging import get_logger
from app.orchestrator.context_window import build_context
from app.orchestrator.sentence_splitter import SentenceSplitter
from app.orchestrator.session_manager import LiveSession

log = get_logger(__name__)

SendFn = Callable[[ServerEvent], Awaitable[None]]
"""Отправка события в сокет. Передаётся снаружи, чтобы pipeline не знал про FastAPI."""


def _wav_duration_ms(data_b64: str) -> int:
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

    # ------------------------------------------------------------------ API

    async def handle_user_message(self, text: str, interrupts: int | None) -> None:
        """Точка входа хода. Реализует §6, шаги 3-5.

        Шаги 1-2 (локальная остановка звука и отправка события) — на клиенте,
        и намеренно: они обязаны укладываться в 300 мс без сетевого
        round-trip. Здесь начинается серверная половина протокола.
        """
        generations = self._session.generations

        # Шаг 3: новое поколение. Инкремент ПЕРВЫМ делом — с этого момента
        # is_stale() уже запрещает отправку хвоста старого поколения.
        gen_id = generations.bump()

        # Шаг 4: снять активные стримы LLM и TTS предыдущего поколения.
        if interrupts is not None:
            await generations.cancel(interrupts)
            # Шаг 5: сообщить клиенту, какое поколение отменено — на случай,
            # если он ещё не знает о новом.
            await self._raw_send(CancelEvent(gen_id=interrupts))

        self._session.add_turn(TurnRole.USER, text)

        task = asyncio.create_task(self._run_turn(gen_id, text))
        generations.register(gen_id, task)

    # -------------------------------------------------------------- внутри

    async def _run_turn(self, gen_id: int, user_text: str) -> None:
        """Один ход целиком. Отменяется целиком по task.cancel()."""
        try:
            await self._speak(gen_id, user_text)
            await self._advance_stage(gen_id, user_text)
        except asyncio.CancelledError:
            log.info("pipeline.turn_cancelled", gen_id=gen_id)
            raise
        except Exception:
            log.exception("pipeline.turn_failed", gen_id=gen_id)
            raise

    async def _speak(self, gen_id: int, user_text: str) -> None:
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
        seq = 0
        elapsed_ms = 0
        """Сколько аудио этого поколения уже отправлено — начало отсчёта для
        следующего SubtitleEvent. Тайминги относительно начала поколения (§7),
        не абсолютное время."""

        async for token in self._ai.stream_character_reply(
            persona=self._session.scenario.persona,
            stage=stage,
            history=context.recent,
            summary=context.summary,
            user_text=user_text,
        ):
            full_text.append(token)
            await self._send(gen_id, TokenEvent(gen_id=gen_id, text=token))

            for sentence in splitter.feed(token):
                seq, elapsed_ms = await self._synthesize(gen_id, sentence, seq, elapsed_ms)

        tail = splitter.flush()
        if tail:
            seq, elapsed_ms = await self._synthesize(gen_id, tail, seq, elapsed_ms)

        self._session.add_turn(TurnRole.AGENT, "".join(full_text))

    async def _synthesize(
        self, gen_id: int, sentence: str, seq: int, elapsed_ms: int
    ) -> tuple[int, int]:
        """Озвучить одно предложение, отдавая чанки по мере готовности (§10).

        Заодно копит длительность и шлёт SubtitleEvent по завершении
        предложения — клиент использует его, чтобы показывать текст в такт
        голосу, а не в такт токенам (токены приходят быстрее речи).
        """
        sentence_ms = 0
        async for chunk in self._speech.stream_tts(
            gen_id=gen_id,
            seq=seq,
            text=sentence,
            voice_id=self._session.scenario.persona.voice_id,
        ):
            await self._send(
                gen_id,
                AudioChunkEvent(
                    gen_id=gen_id, seq=chunk.seq, data=chunk.data, format=chunk.format
                ),
            )
            sentence_ms += _wav_duration_ms(chunk.data)
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

    async def _advance_stage(self, gen_id: int, user_text: str) -> None:
        """Классификация ответа моделью, решение о переходе — кодом (§5)."""
        stage = self._session.machine.stage(self._session.current_stage_id)
        context = build_context(
            self._session.turns, self._max_context_turns, self._session.summary
        )

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
