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
    Action,
    ActionEvent,
    AudioChunkEvent,
    CancelEvent,
    Classification,
    OpeningKind,
    ReportEvent,
    ServerEvent,
    SessionStatus,
    SubtitleEvent,
    TokenEvent,
    Turn,
    TurnRole,
)

from app.clients.ai_client import AiClient
from app.clients.speech_client import SpeechClient
from app.core.logging import get_logger
from app.db.engine import session_factory
from app.db.repositories import SqlReportRepository, SqlSessionRepository
from app.orchestrator.context_window import build_context
from app.orchestrator.fsm import Transition
from app.orchestrator.sentence_splitter import SentenceSplitter
from app.orchestrator.session_manager import LiveSession
from app.tracing import SpanRecorder

log = get_logger(__name__)

SendFn = Callable[[ServerEvent], Awaitable[None]]
"""Отправка события в сокет. Передаётся снаружи, чтобы pipeline не знал про FastAPI."""

_OPENING_DIRECTIVE = {
    OpeningKind.SESSION_START: (
        "[Ты говоришь первым — открой разговор по инструкции в системном промпте.]"
    ),
    OpeningKind.STAGE_TRANSITION: (
        "[Разговор переходит к следующему этапу — продолжи по инструкции в системном промпте.]"
    ),
}
"""Ремарка режиссёра вместо реплики пользователя, когда персонаж говорит сам.

Не косметика: Anthropic Messages API отклоняет пустой список сообщений и
список, не начинающийся с роли user, — а у открывающей реплики реплики
пользователя по определению нет. Содержательная часть инструкции лежит в
системном промпте (ai-service/app/character/prompts.py), здесь — только
непустая затычка нужной роли. См. docs/agent-initiative.md.
"""


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
        # Держит ссылки на fire-and-forget задачи (запись хода в БД), пока
        # они не завершатся — иначе их может собрать GC на середине, это
        # известная ловушка asyncio.create_task без сохранённой ссылки.
        self._background_tasks: set[asyncio.Task[None]] = set()

    def _fire_and_forget(self, coro: Coroutine[object, object, None]) -> None:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    # ------------------------------------------------------------------ API

    async def open_session(self) -> None:
        """Персонаж заговаривает первым — Claude.md §1, «инициативу держит агент».

        Единственная точка входа хода, у которой нет реплики пользователя:
        поколение заводится тем же `bump()` и регистрируется в том же реестре,
        что и обычный ход, поэтому barge-in отменяет открывающую реплику ровно
        так же и без единого специального случая (§6).

        Классификации здесь нет намеренно: классифицировать нечего — сотрудник
        ещё ничего не сказал, а `_advance_stage` двигает автомат по ответу
        пользователя, а не по реплике персонажа.
        """
        generations = self._session.generations
        gen_id = generations.bump()

        task = asyncio.create_task(self._run_opening(gen_id, OpeningKind.SESSION_START))
        generations.register(gen_id, task)

    async def handle_finish_request(self) -> None:
        """Сотрудник нажал «Завершить» — Claude.md §3, действие «завершить».

        В отличие от автоматического завершения, здесь сначала снимаем всё
        активное: персонаж мог говорить в этот момент, и продолжать реплику
        после конца тренировки бессмысленно. Отменять безопасно именно тут —
        вызов приходит из цикла приёма ws.py, то есть из задачи, которой нет
        в реестре поколений; автоматический путь так делать не может, он бы
        отменил сам себя.
        """
        await self._session.generations.cancel_all()
        await self._finish()

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

        user_turn = self._session.add_turn(TurnRole.USER, text)
        # Не await: запись в БД не должна задерживать обработку следующего
        # события в цикле приёма — от этого зависит бюджет barge-in (§9).
        self._fire_and_forget(self._persist_turn(user_turn, gen_id))

        task = asyncio.create_task(self._run_turn(gen_id, text))
        generations.register(gen_id, task)

    # -------------------------------------------------------------- внутри

    async def _run_turn(self, gen_id: int, user_text: str) -> None:
        """Один ход целиком. Отменяется целиком по task.cancel()."""
        recorder = SpanRecorder(self._session.session_id, gen_id)
        try:
            await self._speak(gen_id, user_text, recorder)
            transition = await self._advance_stage(gen_id, user_text, recorder)

            # Этап сменился — персонаж сам открывает новый, не дожидаясь
            # следующей реплики сотрудника (§1). Тем же поколением: это
            # продолжение той же задачи, и barge-in снимает его целиком.
            if transition.action is Action.NEXT_STAGE:
                await self._speak(
                    gen_id,
                    _OPENING_DIRECTIVE[OpeningKind.STAGE_TRANSITION],
                    recorder,
                    opening_kind=OpeningKind.STAGE_TRANSITION,
                )
            elif transition.action is Action.EVALUATE:
                # Последний этап пройден — сценарий окончен (§3).
                await self._finish()
        except asyncio.CancelledError:
            log.info("pipeline.turn_cancelled", gen_id=gen_id)
            raise
        except Exception:
            log.exception("pipeline.turn_failed", gen_id=gen_id)
            raise

    async def _run_opening(self, gen_id: int, opening_kind: OpeningKind) -> None:
        """Открывающая реплика без предшествующего хода пользователя."""
        recorder = SpanRecorder(self._session.session_id, gen_id)
        try:
            await self._speak(
                gen_id,
                _OPENING_DIRECTIVE[opening_kind],
                recorder,
                opening_kind=opening_kind,
            )
        except asyncio.CancelledError:
            log.info("pipeline.opening_cancelled", gen_id=gen_id)
            raise
        except Exception:
            # Открывающую реплику некому «переспросить»: сотрудник ещё ничего
            # не сказал и в тишине не поймёт, что делать. Поэтому, в отличие
            # от обычного хода, здесь есть запасной путь без LLM.
            log.exception("pipeline.opening_failed", gen_id=gen_id)
            await self._speak_fallback_opening(gen_id, recorder)

    async def _finish(self) -> None:
        """Завершить сессию. Общее тело для обоих триггеров, идемпотентное.

        Оверлей у сотрудника поднимается по ActionEvent(finish) сразу, а не по
        готовому отчёту: оценка — вызов сильной модели (таймаут 120 с), а
        отчёта сотрудник всё равно не видит, это экран методиста (§2).
        """
        # Проверка-и-установка без await между ними: в одном event loop это
        # атомарно, поэтому гонка «кнопка + автомат» разрешается сама.
        if self._session.status is SessionStatus.FINISHED:
            log.debug("pipeline.finish_ignored_already_finished")
            return
        self._session.status = SessionStatus.FINISHED

        log.info("pipeline.session_finished", stage_id=self._session.current_stage_id)

        await self._mark_finished()

        # Через _raw_send, а не _send: событие не принадлежит поколению, и
        # фильтр устаревания к нему неприменим — так же отправляется CancelEvent.
        await self._raw_send(
            ActionEvent(
                gen_id=self._session.generations.current,
                action=Action.FINISH,
                stage_id=self._session.current_stage_id,
            )
        )

        self._fire_and_forget(self._evaluate_and_store())

    async def _mark_finished(self) -> None:
        """Зафиксировать завершение в БД сразу, не дожидаясь дисконнекта."""
        try:
            async with session_factory()() as db:
                await SqlSessionRepository(db).mark_finished(self._session.session_id)
        except Exception:
            log.exception("pipeline.mark_finished_failed")

    async def _evaluate_and_store(self) -> None:
        """Оценка сильной моделью и сохранение отчёта (§7).

        Намеренно НЕ регистрируется в реестре поколений: сотрудник может уйти
        на главную сразу после завершения, и тогда `cancel_all()` в ws.py убил
        бы оценку раньше, чем отчёт сохранится. Ссылку на задачу держит
        _background_tasks, поэтому закрытие сокета ей ничего не делает.

        Порядок «сначала БД, потом сокет» — по той же причине: отчёт нужен
        методисту, а сокета сотрудника к этому моменту может уже не быть.
        """
        session = self._session
        try:
            report = await self._ai.evaluate(
                session_id=session.session_id,
                scenario=session.scenario,
                transcript=list(session.turns),
                duration_sec=session.elapsed_sec,
                stages_completed=len(session.stage_history),
                stages_total=len(session.scenario.stages),
            )
        except Exception:
            # Сессия уже завершена, выход сотруднику это не ломает — но
            # методист останется без отчёта, поэтому логируем громко.
            log.exception("pipeline.evaluation_failed", session_id=session.session_id)
            return

        try:
            async with session_factory()() as db:
                await SqlReportRepository(db).save(report)
        except Exception:
            log.exception("pipeline.report_save_failed", session_id=session.session_id)
            return

        log.info("pipeline.report_saved", total_score=report.total_score)

        try:
            await self._raw_send(
                ReportEvent(
                    gen_id=session.generations.current,
                    session_id=session.session_id,
                    report=report,
                )
            )
        except Exception:  # noqa: BLE001 — тип исключения принадлежит транспорту
            # Сокет уже закрыт — штатный исход (сотрудник ушёл на главную сразу
            # после завершения), поэтому info, а не exception: отчёт сохранён и
            # доступен методисту по GET /sessions/{id}/report.
            #
            # Ловим широко намеренно: `_raw_send` внедряется снаружи (SendFn),
            # и pipeline по замыслу не знает, что там FastAPI — сузить тип
            # значило бы затащить сюда транспорт.
            log.info("pipeline.report_not_delivered_socket_closed")

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
        self,
        gen_id: int,
        user_text: str,
        recorder: SpanRecorder,
        opening_kind: OpeningKind | None = None,
    ) -> None:
        """Реплика персонажа: токены LLM → предложения → чанки TTS.

        `opening_kind` заполнен, когда персонаж говорит сам (§1); тогда в
        `user_text` лежит ремарка режиссёра, а не текст сотрудника.

        TODO: параллельный запуск TTS для предложения N и продолжение чтения
        токенов N+1 — сейчас последовательно, и это съедает time to first
        audio на длинных ответах.
        """
        persona = self._session.scenario.persona
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

        async with recorder.span("character_reply", self._speak_label(user_text, opening_kind)):
            # Самопредставление персонажа приходит первым токеном потока и не
            # генерируется моделью (ai-service/app/api/character.py): оно
            # детерминировано, поэтому сплиттер отдаёт его в TTS ещё до того,
            # как LLM напишет первое слово продолжения (§9, метрика 1).
            async for token in self._ai.stream_character_reply(
                persona=persona,
                stage=stage,
                history=context.recent,
                summary=context.summary,
                user_text=user_text,
                opening_kind=opening_kind,
                off_topic_streak=self._session.off_topic_streak,
            ):
                full_text.append(token)
                await self._send(gen_id, TokenEvent(gen_id=gen_id, text=token))

                for sentence in splitter.feed(token):
                    seq, elapsed_ms = await self._synthesize(
                        gen_id, sentence, seq, elapsed_ms, recorder
                    )

            tail = splitter.flush()
            if tail:
                seq, elapsed_ms = await self._synthesize(gen_id, tail, seq, elapsed_ms, recorder)

        await self._record_agent_turn(gen_id, "".join(full_text))

    async def _record_agent_turn(self, gen_id: int, text: str) -> None:
        """Записать реплику персонажа в историю — если её вообще слышали.

        Устаревшее поколение сюда доходить может: `_send` погасил его чанки
        (§6), но сам генератор продолжал работать до конца. Записывать такую
        реплику нельзя — сотрудник её не слышал, а транскрипт целиком уходит
        в оценку методисту (§7) и в отчёт. Плюс `add_turn` проставил бы ей
        ЭТАП НА МОМЕНТ ЗАВЕРШЕНИЯ, который к этому тексту уже не относится.
        """
        if self._session.generations.is_stale(gen_id):
            log.info("pipeline.dropped_stale_turn", gen_id=gen_id, chars=len(text))
            return

        agent_turn = self._session.add_turn(TurnRole.AGENT, text)
        await self._persist_turn(agent_turn, gen_id)

    def _speak_label(self, user_text: str, opening_kind: OpeningKind | None) -> str:
        """Подпись спана для Gantt-графика админ-панели.

        У открывающей реплики в `user_text` лежит ремарка режиссёра — тащить
        её в подпись бессмысленно, там полезнее этап, который открывают.
        """
        persona_name = self._session.scenario.persona.name
        if opening_kind is not None:
            return f'{persona_name}: открывает этап "{self._session.current_stage_id}"'
        return f'{persona_name}: ответ на "{user_text[:60]}"'

    async def _speak_fallback_opening(self, gen_id: int, recorder: SpanRecorder) -> None:
        """Открывающая реплика без LLM — последнее средство при сбое модели.

        Компромисс осознанный (docs/agent-initiative.md, открытый вопрос):
        `agent_opening` из сценария озвучивается дословно, чего мы в норме
        избегаем, — но альтернатива здесь не «чуть хуже сформулировано», а
        полная тишина в начале сессии, когда сотруднику не на что реагировать.
        Методист писал эту фразу как самостоятельную реплику, так что звучит
        она осмысленно и сама по себе. Для обычного хода такого запасного пути
        нет и не нужно: там сбой случается после реплики человека, и её можно
        повторить.
        """
        stage = self._session.machine.stage(self._session.current_stage_id)
        text = stage.agent_opening

        try:
            async with recorder.span("character_reply_fallback", text[:120]):
                await self._send(gen_id, TokenEvent(gen_id=gen_id, text=text))
                await self._synthesize(gen_id, text, 0, 0, recorder)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("pipeline.opening_fallback_failed", gen_id=gen_id)
            return

        await self._record_agent_turn(gen_id, text)

    async def _synthesize(
        self, gen_id: int, sentence: str, seq: int, elapsed_ms: int, recorder: SpanRecorder
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

    async def _advance_stage(
        self, gen_id: int, user_text: str, recorder: SpanRecorder
    ) -> Transition:
        """Классификация ответа моделью, решение о переходе — кодом (§5)."""
        stage = self._session.machine.stage(self._session.current_stage_id)
        context = build_context(
            self._session.turns, self._max_context_turns, self._session.summary
        )

        try:
            async with recorder.span("classify", f'Критерий этапа "{stage.id}"'):
                classification: Classification = await self._ai.classify(
                    stage=stage, history=context.recent, user_text=user_text
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            # Сбой классификации не имеет права останавливать сценарий. Раньше
            # исключение уходило наверх, decide() не вызывался — а вместе с ним
            # не срабатывал и принудительный переход по max_turns: на живой
            # сессии два подряд таймаута classify (30 с каждый) дали этапу
            # перешагнуть свой лимит на два хода, и сценарий не дошёл до финала.
            # Считаем ход неполным: этап не засчитывается, но счётчик тикает.
            # Перехват СНАРУЖИ recorder.span — чтобы спан всё равно записался
            # со статусом error и сбой было видно в админ-панели.
            log.exception("pipeline.classify_failed", gen_id=gen_id, stage_id=stage.id)
            classification = Classification.INCOMPLETE

        # Счётчик уходов от темы — только для тона следующей реплики персонажа
        # (§1). В автомат он не передаётся: `decide()` по-прежнему не различает
        # off_topic и incomplete, возврат в русло — работа персонажа.
        self._session.off_topic_streak = (
            self._session.off_topic_streak + 1
            if classification is Classification.OFF_TOPIC
            else 0
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
        return transition

    async def _send(self, gen_id: int, event: ServerEvent) -> None:
        """Отправка с проверкой поколения.

        Единственный разрешённый путь наружу для событий, привязанных к
        поколению. Если поколение устарело — событие молча гасится: это и
        есть «ни один чанк старого поколения не воспроизводится» (§6).
        """
        if self._session.generations.is_stale(gen_id):
            # `event_type`, а не `event`: у structlog `event` — это само
            # сообщение (первый позиционный аргумент), и одноимённый kwarg
            # роняет вызов с TypeError. Ловилось это только здесь, на пути
            # отброса устаревшего чанка, то есть ровно в метрике 4.
            log.debug("pipeline.dropped_stale", gen_id=gen_id, event_type=event.type)
            return
        await self._raw_send(event)
