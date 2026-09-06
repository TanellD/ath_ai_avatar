"""Lifecycle одной PTT capture внутри gateway WebSocket-сессии."""

import asyncio
import time
from dataclasses import dataclass

from ath_contracts import (
    ErrorEvent,
    SpeechStart,
    SpeechStartedEvent,
    TranscriptEvent,
    VoiceProviderSwitchedEvent,
)
from ath_contracts.api import (
    SttFaultEvent,
    SttFinalEvent,
    SttOpenRequest,
    SttProviderSwitchedEvent,
    SttTranscriptEvent,
)

from app.clients.speech_client import SpeechClient, SttStream
from app.core.logging import get_logger
from app.orchestrator.pipeline import SendFn, TurnPipeline
from app.orchestrator.voice_recovery import VoiceRecoveryPlayer

log = get_logger(__name__)

# Формат, в котором клиент обязан присылать PCM (см. events.py::SpeechStart и
# useMicCapture.ts) — тот же канонический формат, что speech-service объявляет
# в app/stt/capture_buffer.py (CANONICAL_SAMPLE_RATE/SAMPLE_WIDTH_BYTES).
# Одна и та же пара чисел заведена дважды, а не через общий импорт: gateway и
# speech-service — разные пакеты с разными зависимостями. Клиент формат не
# сверяет (SpeechStart.sample_rate/audio_format летят, но не проверяются) —
# если он когда-нибудь изменится, этот лимит молча станет неверным.
_PCM_SAMPLE_RATE_HZ = 16_000
_PCM_SAMPLE_WIDTH_BYTES = 2


@dataclass
class _ActiveCapture:
    capture_id: str
    gen_id: int
    provider_epoch: int
    stream: SttStream
    max_bytes: int
    received_bytes: int = 0
    finalizing: bool = False
    reader_task: asyncio.Task[None] | None = None
    watchdog_task: asyncio.Task[None] | None = None
    started_at: float = 0.0
    finalize_requested_at: float | None = None
    first_partial_seen: bool = False


class VoiceTurnRegistry:
    def __init__(
        self,
        *,
        session_id: str,
        pipeline: TurnPipeline,
        speech: SpeechClient,
        send: SendFn,
        max_capture_seconds: int,
        max_frame_bytes: int,
        language: str,
        recovery: VoiceRecoveryPlayer | None = None,
        context_terms: tuple[str, ...] = (),
    ) -> None:
        self._session_id = session_id
        self._pipeline = pipeline
        self._speech = speech
        self._send = send
        self._max_frame_bytes = max_frame_bytes
        self._max_capture_seconds = max_capture_seconds
        self._language = language
        self._recovery = recovery
        self._context_terms = context_terms
        self._active: _ActiveCapture | None = None
        self._lock = asyncio.Lock()

    async def start(self, event: SpeechStart) -> None:
        async with self._lock:
            if self._active is not None:
                await self._send(
                    ErrorEvent(
                        gen_id=self._active.gen_id,
                        code="voice_capture_active",
                        message="Завершите текущую голосовую реплику",
                    )
                )
                return

            gen_id = await self._pipeline.begin_user_turn(event.interrupts)
            request = SttOpenRequest(
                session_id=self._session_id,
                capture_id=event.capture_id,
                provider_epoch=0,
                language=self._language,
                context_terms=list(self._context_terms),
            )
            try:
                stream = await self._speech.open_stt(request)
            except Exception:  # noqa: BLE001 - boundary maps downstream failures to protocol error
                await self._send(
                    ErrorEvent(
                        gen_id=gen_id,
                        code="stt_unavailable",
                        message="Распознавание речи недоступно; используйте текстовый ввод",
                    )
                )
                return

            active = _ActiveCapture(
                capture_id=str(event.capture_id),
                gen_id=gen_id,
                provider_epoch=0,
                stream=stream,
                max_bytes=self._max_capture_seconds
                * _PCM_SAMPLE_RATE_HZ
                * _PCM_SAMPLE_WIDTH_BYTES,
                started_at=time.monotonic(),
            )
            self._active = active
            active.reader_task = asyncio.create_task(self._read_events(active))
            active.watchdog_task = asyncio.create_task(self._watchdog(active))
            await self._send(
                SpeechStartedEvent(gen_id=gen_id, capture_id=event.capture_id)
            )
            log.info(
                "voice.capture_started",
                capture_id=active.capture_id,
                gen_id=gen_id,
                provider_epoch=active.provider_epoch,
            )

    async def push(self, frame: bytes) -> None:
        async with self._lock:
            active = self._active
            if active is None or active.finalizing:
                # Последний MediaStream frame и добавленная клиентом trailing
                # silence могут добраться уже после speech_end/watchdog. Это
                # штатная гонка завершения, а не ошибка пользователя.
                log.debug(
                    "voice.late_frame_dropped",
                    frame_bytes=len(frame),
                    capture_finalizing=active is not None,
                )
                return
            if not frame or len(frame) % 2 or len(frame) > self._max_frame_bytes:
                await self._abort_locked(active, "invalid_audio_frame")
                return
            if active.received_bytes + len(frame) > active.max_bytes:
                await self._finalize_locked(active)
                return
            active.received_bytes += len(frame)
            await active.stream.push(frame)

    async def end(self, capture_id: str) -> None:
        async with self._lock:
            active = self._active
            if active is None or active.capture_id != capture_id:
                return
            await self._finalize_locked(active)

    async def abort(self, capture_id: str) -> None:
        async with self._lock:
            active = self._active
            if active is None or active.capture_id != capture_id:
                return
            await self._abort_locked(active, "capture_aborted", notify=False)

    async def aclose(self) -> None:
        async with self._lock:
            if self._active is not None:
                await self._abort_locked(self._active, "connection_closed", notify=False)

    async def _finalize_locked(self, active: _ActiveCapture) -> None:
        if active.finalizing:
            return
        active.finalizing = True
        active.finalize_requested_at = time.monotonic()
        if active.watchdog_task is not None:
            active.watchdog_task.cancel()
        await active.stream.finalize()
        log.info(
            "voice.finalize_requested",
            capture_id=active.capture_id,
            gen_id=active.gen_id,
            duration_ms=round((active.finalize_requested_at - active.started_at) * 1000),
        )

    async def _abort_locked(
        self, active: _ActiveCapture, code: str, *, notify: bool = True
    ) -> None:
        if active.watchdog_task is not None:
            active.watchdog_task.cancel()
        if active.reader_task is not None:
            active.reader_task.cancel()
        await active.stream.aclose()
        if self._active is active:
            self._active = None
        log.info(
            "voice.capture_aborted",
            capture_id=active.capture_id,
            gen_id=active.gen_id,
            code=code,
        )
        if notify:
            await self._send(
                ErrorEvent(
                    gen_id=active.gen_id,
                    code=code,
                    message="Голосовая реплика отменена; используйте текстовый ввод",
                )
            )


    async def _report_lost_turn(self, active: _ActiveCapture, code: str, message: str) -> None:
        """Сообщить о потерянном ходе — по возможности голосом персонажа.

        Красный баннер посреди голосового разговора рвёт роль сильнее, чем
        живая фраза «повторите, пожалуйста». ErrorEvent уходит в любом случае:
        клиенту нужно сбросить состояние захвата, а `spoken` говорит ему, что
        показывать баннер поверх уже сказанного не надо.
        """
        spoken = False
        if self._recovery is not None:
            spoken = await self._recovery.play(active.gen_id)
        await self._send(
            ErrorEvent(gen_id=active.gen_id, code=code, message=message, spoken=spoken)
        )

    async def _watchdog(self, active: _ActiveCapture) -> None:
        try:
            await asyncio.sleep(self._max_capture_seconds)
            async with self._lock:
                if self._active is active:
                    await self._finalize_locked(active)
        except asyncio.CancelledError:
            return

    async def _read_events(self, active: _ActiveCapture) -> None:
        terminal_event = False
        try:
            async for event in active.stream.events():
                if self._active is not active or str(event.capture_id) != active.capture_id:
                    continue
                if event.provider_epoch < active.provider_epoch:
                    continue
                if event.provider_epoch > active.provider_epoch:
                    # The speech-service owns provider epochs. Only the next epoch
                    # is a valid in-turn Soniox -> GigaAM transition.
                    if event.provider_epoch != active.provider_epoch + 1:
                        continue
                    active.provider_epoch = event.provider_epoch
                    active.first_partial_seen = False
                    log.warning(
                        "voice.provider_epoch_changed",
                        capture_id=active.capture_id,
                        gen_id=active.gen_id,
                        provider=event.provider,
                        provider_epoch=active.provider_epoch,
                    )
                if isinstance(event, SttProviderSwitchedEvent):
                    # Клиент узнаёт не про сбой, а про то, что партиалов больше
                    # не будет: иначе замерший черновик читается как «не слышат».
                    await self._send(
                        VoiceProviderSwitchedEvent(
                            gen_id=active.gen_id,
                            capture_id=event.capture_id,
                            provider_epoch=event.provider_epoch,
                            provider=event.provider,
                            partials_available=event.partials_available,
                        )
                    )
                elif isinstance(event, SttTranscriptEvent):
                    if not active.first_partial_seen:
                        active.first_partial_seen = True
                        log.info(
                            "voice.first_partial",
                            capture_id=active.capture_id,
                            gen_id=active.gen_id,
                            latency_ms=round((time.monotonic() - active.started_at) * 1000),
                        )
                    await self._send(
                        TranscriptEvent(
                            gen_id=active.gen_id,
                            capture_id=event.capture_id,
                            provider_epoch=event.provider_epoch,
                            provider=event.provider,
                            text=event.text,
                            is_final=False,
                            stt_confidence=event.confidence,
                        )
                    )
                elif isinstance(event, SttFinalEvent):
                    terminal_event = True
                    finalization_ms = (
                        round((time.monotonic() - active.finalize_requested_at) * 1000)
                        if active.finalize_requested_at is not None
                        else None
                    )
                    await self._send(
                        TranscriptEvent(
                            gen_id=active.gen_id,
                            capture_id=event.capture_id,
                            provider_epoch=event.provider_epoch,
                            provider=event.provider,
                            text=event.text,
                            is_final=True,
                            stt_confidence=event.confidence,
                        )
                    )
                    committed = await self._pipeline.handle_voice_final(
                        gen_id=active.gen_id,
                        capture_id=active.capture_id,
                        text=event.text,
                        confidence=event.confidence,
                    )
                    if not event.text.strip():
                        # Распознавание отработало, но текста нет. Для человека
                        # это неотличимо от «меня не услышали», и ход потерян.
                        await self._report_lost_turn(
                            active, "stt_empty_final", "Речь не распознана"
                        )
                    log.info(
                        "voice.final_received",
                        capture_id=active.capture_id,
                        gen_id=active.gen_id,
                        provider=event.provider,
                        finalization_ms=finalization_ms,
                        committed=committed,
                    )
                    return
                elif isinstance(event, SttFaultEvent):
                    terminal_event = True
                    await self._report_lost_turn(
                        active,
                        f"stt_{event.kind}",
                        "Не удалось распознать речь; используйте текстовый ввод",
                    )
                    return
            if not terminal_event:
                await self._report_lost_turn(
                    active,
                    "stt_disconnected",
                    "Распознавание прервалось; используйте текстовый ввод",
                )
        except Exception:  # noqa: BLE001 - downstream boundary
            await self._report_lost_turn(
                active,
                "stt_disconnected",
                "Распознавание прервалось; используйте текстовый ввод",
            )
        finally:
            # `_abort_locked` (start/end/abort/aclose, все под self._lock) может
            # выполняться конкурентно с этим finally — оно не под локом, потому
            # что выполняется внутри самой reader_task, снаружи вызова с
            # `async with self._lock`. Без лока здесь `self._active = None` и
            # отмена watchdog гонялись бы с той же мутацией из `_abort_locked`.
            # `stream.aclose()` оставлен вне лока: закрытие websocket безопасно
            # вызывать конкурентно (библиотека идемпотентна), а долгий await
            # под локом задержал бы другие операции этой capture.
            await active.stream.aclose()
            async with self._lock:
                if active.watchdog_task is not None:
                    active.watchdog_task.cancel()
                if self._active is active:
                    self._active = None
