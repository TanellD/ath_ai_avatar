# Voice Input / Turn Intelligence: план реализации

Статус: **в реализации**. Phase 0 foundation завершён; Phase 1 PTT + Soniox
прошёл автоматические проверки и ручную проверку в браузере. Phase 2 GigaAM local
завершён: изолированный worker с preload/readiness и ограниченной очередью,
`make gigaam-setup` с закреплёнными в `models.lock.json` контрольными суммами и
офлайновый штатный старт. Phase 3 automatic failover реализован в основном:
epoch, lossless replay, 5-секундный finalize-watchdog и объявление смены
провайдера клиенту через `voice_provider_switched`. Не закрыто: часть
обязательных fault-кейсов §L без тестов (поздний Soniox final после failover,
недоступный GigaAM, оба порядка final/disconnect), отдельный ADR, прогон
benchmark на реальном корпусе и hands-free. Это единственный актуальный
источник решений по голосовому вводу; [`stt-phase.md`](stt-phase.md) — только
инвентарь подготовленного кода.

Основания: **product** — требования; **code** — текущий репозиторий;
**provider/runtime** — официальные Soniox/GigaAM; **benchmark** — наши замеры и
ADR. Чужие voice-agent реализации не являются blueprint; thresholds, policies
и эвристики из них не переносятся.

## A. What stays

1. PTT — первый vertical slice. Первый клик явно означает новый turn: локально
   остановить playback, создать один `gen_id`, начать capture/STT; второй клик —
   finalize. Toggle-to-talk выбран после проверки на тачпаде: удержание оказалось
   неудобным, при этом явные границы turn сохраняются.
2. Gateway владеет generation lifecycle. Provider не создаёт dialogue
   generation; после final transcript второй bump запрещён.
3. Audio идёт binary: browser → gateway → speech-service. Основной
   `SONIOX_API_KEY` не попадает в браузер; JSON/base64 не используется.
4. Одна active capture/session; `capture_id` отсекает late capture events.
5. MVP отправляет в LLM только committed final transcript. Partial — UI,
   telemetry и будущая stability/speculation.
6. Text input остаётся независимым fallback. После commit оба входа создают
   один `CommittedUserTurn` и используют существующий LLM/TTS/FSM pipeline.
7. STT terms формируются из сценария/базы знаний, без второго словаря.

## B. What changes

- Soniox realtime — primary; обязательный fallback — локальный GigaAM-v3,
  а не другой cloud API.
- Provider objects скрыты за normalized events/capabilities.
- `SttProviderManager` централизует health, epoch, failover и recovery.
- Lossless audio текущего uncommitted turn хранится до commit/abort и при
  падении Soniox целиком replay-ится в GigaAM.
- `capture_id` дополняется `provider_epoch`; exactly-once обеспечивает
  атомарный gateway commit arbiter + DB uniqueness.
- PTT сразу cancel. Hands-free VAD onset только создаёт candidate и локально
  duck-ит playback; bump/cancel — после подтверждения interruption.
- Raw audio storage/evidence вынесен после core MVP: обязательные требования
  не оправдывают privacy/infra scope сейчас.

## C. Current architecture fit

| Текущий файл/компонент | Роль в фиче |
|---|---|
| `frontend/pages/TraineeSession.tsx` | mic lifecycle, output gate, transcript UI |
| `frontend/audio/cancelPlayback.ts` | необратимый PTT/confirmed-interrupt cancel |
| `frontend/audio/AudioQueue.ts` | второй `gen_id`-фильтр stale audio |
| `frontend/ws/useSessionSocket.ts` | JSON control/events + binary frames + stale gate |
| `gateway/orchestrator/generation.py` | authoritative bump/cancel/is_stale |
| `gateway/orchestrator/pipeline.py` | committed turn → существующий LLM/TTS flow |
| `gateway/orchestrator/session_manager.py` | live FSM + voice capture registry |
| `gateway/db/repositories.py` | idempotent voice Turn commit |
| `speech-service/app/stt/base.py` | перерабатываемая provider abstraction |
| `packages/contracts/ath_contracts/events.py` | Python source of truth для WS |

Уже заготовлены `useMicCapture`, `useVad`, PTT UI, `listening/recognizing`,
`TranscriptEvent`, `stt_confidence/audio_ref` и STT namespace. Но текущий
`LiveSession.add_turn()` меняет память до отдельного DB `append_turn()`, поэтому
не доказывает exactly-once для voice path.

## D. Proposed architecture

```text
MicCapture → PCM worklet → LocalCaptureGate
                    │ binary PCM
                    ▼
Gateway: VoiceTurnRegistry → TurnIntelligence → CommitArbiter
                    │                              │
                    ▼                              ▼
speech-service: CaptureBuffer              existing TurnPipeline
       → SttProviderManager
          ├─ Soniox realtime
          └─ GigaAmSttProvider → isolated local worker
```

- `MicCapture`: permission/device, downmix, единственный resampling, PCM/sample
  clock.
- `LocalCaptureGate`: блокирует старый output до PTT ACK; позже делает duck.
- `VoiceTurnRegistry`: capture state, gen, epoch, watchdog, per-capture lock.
- `TurnIntelligence` (gateway): commit/candidate/backchannel/endpoint policy;
  provider-neutral.
- `SttProviderManager` (speech-service): selection, capabilities, health,
  stall, failover, recovery, telemetry.
- `CaptureBuffer`: bounded canonical PCM для mid-turn replay.
- `gigaam-worker`: отдельный local process/container, preload и bounded queue;
  CPU inference не блокирует asyncio loops.
- `CommitArbiter`: единственная точка `COMMITTED`, DB idempotency и LLM start.

## E. Provider contract

```text
ProviderCapabilities:
  streaming_partials, confidence, token_timestamps,
  semantic_endpoint, context_terms, manual_finalize

Normalized event identity:
  session_id, capture_id, provider_epoch, provider, monotonic_timestamp

RecognitionProgress(audio_samples_processed)
TranscriptHypothesis(text, is_final, confidence?, start_sample?, end_sample?)
EndpointObserved(kind=semantic|manual|local_vad)
FinalizationComplete(text, aggregate_confidence?, token_spans?)
ProviderFault(kind, retryable, provider_request_id?)
```

Soniox FULL поддерживает partials/confidence/timestamps/semantic endpoint/
terms. GigaAM LOCAL DEGRADED обязан дать final, остальные поля optional. Нельзя
подделывать отсутствующую confidence. Soniox final tokens стабильны, но commit
разрешён только после authoritative `<fin>`/`<end>`.

Provider API концептуально: `open(config)`, `push(pcm)`, `finalize()`,
`events()`, `aclose()`; точные Python signatures фиксируются после SDK/runtime
spike и contract tests.

## F. Voice turn lifecycle

### PTT (MVP)

```text
первый клик по кнопке записи
→ local cancelPlayback + output_gate=BLOCKED + capture_id
→ speech_start
→ gateway validates, bumps once, cancels old, returns SpeechStarted(gen_id)
→ Soniox + CaptureBuffer; PCM stream; active partial UI
второй клик/watchdog → speech_end → manual finalize
→ CommitArbiter → DB insert once → existing TurnPipeline(gen_id, final_text)
```

До ACK frontend отбрасывает все token/audio/subtitle/action старой generation,
даже если server gen ещё не изменился. При потере ACK старый output не
возобновляется: capture abort, voice error, text fallback.

`pointercancel`, lost pointer capture, release вне элемента,
`visibilitychange`, device ended, WS close и max-duration watchdog вызывают
один idempotent `finalize_or_abort` — session не зависает в CAPTURING.

### Hands-free (later)

```text
IDLE → CANDIDATE_LISTENING → local DUCK (без bump/cancel)
→ INTERRUPTION_CONFIRMED | BACKCHANNEL | NOISE_OR_ECHO | UNKNOWN
```

Confirmed promoted в capture и только тогда bump/cancel. Остальные ветки
resume/continue и не меняют dialogue state. Вначале reversible primitive —
gain duck: WebAudio BufferSource нельзя честно pause/resume без перестройки
очереди. Настоящий pause добавляется лишь если собственный UX benchmark этого
потребует. Echo evidence использует AEC + temporal overlap + similarity с
текущим playback window, не со всем текстом ответа.

## G. Failover state machine

```text
SELECTING → PRIMARY_ACTIVE(epoch=N) | LOCAL_PENDING(epoch=N+1)
PRIMARY_ACTIVE → FINALIZING | FAILING_OVER(epoch=N+1)
FAILING_OVER → freeze old epoch → replay buffer → LOCAL_ACTIVE
LOCAL_ACTIVE → FINALIZING | ABORTED + text fallback
FINALIZING → COMMITTING → COMMITTED
```

Soniox восстанавливается только между turns. Provider stall определяется по
progress (audio отправляется, но нет first partial; finalize без completion),
не только по socket close. Watchdog values — Phase 0 test configuration/ADR.

Race final ↔ failure решает per-capture lock:

- authoritative final первым перевёл в COMMITTING — close не запускает local;
- failure первым увеличил epoch — late Soniox final отбрасывается;
- GigaAM активен — любое событие старого epoch отбрасывается.

## H. Turn Intelligence state machine

MVP: `IDLE → PTT_CAPTURING → FINALIZING → COMMITTING → COMMITTED`, из любого
незавершённого state возможен `ABORTED`.

Extensions: `CANDIDATE_LISTENING → INTERRUPTION_CONFIRMED | BACKCHANNEL |
NOISE_OR_ECHO | UNKNOWN`. `WORKING_TRANSCRIPT` никогда не равен committed turn.
Self-correction остаётся рабочей гипотезой до final.

После корректности: `PREPARE` → cancellable `LLM_PREFILL` → лишь затем
`SPEECH_SPECULATION`. В MVP нет user-visible speculation. Stability позже
выводится из stable prefix, suffix churn, возраста prefix и confidence;
лексика/thresholds — только наш corpus/ADR.

## I. Cancellation and exactly-once

| ID | Владелец | Закрывает |
|---|---|---|
| `gen_id` | gateway | stale dialogue/LLM/TTS output |
| `capture_id` | frontend + gateway validation | late audio/transcript другой capture |
| `provider_epoch` | speech-service | late provider event после failover |

Проверка: active capture → capture match → epoch match → valid state → atomic
commit transition → DB unique insert → LLM.

- Per-capture lock разрешает только `FINALIZING → COMMITTING`.
- В `turns` добавляется nullable `capture_id` и unique `(session_id,capture_id)`.
- `commit_voice_turn()` транзакционно возвращает `inserted|already_committed`.
- Только `inserted` обновляет live memory и запускает LLM.
- DB failure не запускает LLM; показывается error + text fallback.

Stale protection распространяется на `useSessionSocket`, `AudioQueue` до/после
decode, subtitles, HeadAudio reset, face/body animations, gestures и delayed
callbacks. Все будущие команды несут `gen_id`; fault tests задерживают каждый
тип sink. После cancel видимый/слышимый stale count обязан быть 0.

## J. Audio buffering

Канонический формат: **mono PCM signed 16-bit little-endian, 16 kHz**.

- AudioWorklet читает фактический device Float32 rate, один раз делает downmix,
  stateful resampling и PCM16 quantization.
- Gateway/speech-service только валидируют и считают samples, не resample.
- Soniox: raw `pcm_s16le`, 16000, 1 channel.
- GigaAM adapter: PCM → in-memory tensor без lossy encode/second resampling.
- Timestamps: `total_samples / 16000`, не wall clock; drift test обязателен.

Authoritative buffer живёт в speech-service. PTT хранит весь uncommitted turn,
после commit/abort память очищается. Начальный dev guard — 20 s: официальный
GigaAM short `.transcribe()` ограничен 25 s. Это 640000 bytes (~625 KiB).
`VOICE_MAX_CAPTURE_SECONDS` уточняется benchmark. Gateway независимо ограничивает
frames/bytes/duration и одну capture/session. Hands-free добавит bounded pre-roll.
Permanent raw storage не входит в core MVP.

## K. Metrics and telemetry

Events: capture start/end/abort, start sent/acked, provider selected/connected/
progress/error/stall/recovered, first partial/partial/endpoint/final, failover
and replay start/end, commit start/success/duplicate-drop, duck/resume,
interruption confirmed, old gen cancelled, stale drop, transport rejection.
Raw audio/partial text в обычные logs не пишутся.

Формулы на frontend monotonic clock:

- `barge_in_silence = playback_silent - acoustic_or_ptt_onset`;
- `first_partial = first_partial_visible - capture_start`;
- `finalization = final_visible - speech_end`;
- `response_ttfa = first_response_audio - speech_end`.

Внутренние spans связываются `session/capture/epoch`, но часы разных машин
напрямую не вычитаются. Hard acceptance: confirmed interruption → silence
≤300 ms; speech end → first response audio ≤3 s; stale audio = 0; lost and
duplicate committed turns = 0. Остальные p50/p95/thresholds — после baseline.

## L. Testing and fault injection

Собственный corpus: 30–50+ русских реплик, два голоса, headset/speakers;
имена, компании, суммы, проценты, даты, отрицания, corrections, паузы,
backchannels, шум и barge-in. Метрики: WER, critical entities, lost/added
negations, endpoint latency, partial churn.

- Unit: resampler/chunks/sample clock, normalized events, capabilities, CAS,
  buffer bounds, epoch filter.
- Contract: Python/TS parity; JSON+binary order; invalid format/frame/state.
- Integration: fake providers, partial corrections, empty final, timeout,
  reconnect, two captures, text/voice alternation.
- Browser: permission/device/pointer/background/refresh/WS/max-hold/silence.
- Acoustic: AEC, headset/speakers, echo/noise/hesitation/barge-in.

Mandatory fault cases: primary unavailable before turn; Soniox mid-turn fail +
buffer replay; late Soniox final; recovery only next turn; local unavailable;
stall without close; both final/disconnect orders; delayed old event каждого
user-visible sink. Debug faults доступны только dev/test server config.

## M. Phases and PRs

0. **Benchmark + contracts (foundation готов, измерения GigaAM впереди):** corpus, Soniox, GigaAM-v3 220M CTC/RNNT/e2e,
   CPU cold/warm/RTF/RAM/weights/direct PCM; normalized events, fake providers,
   ADR runtime/model/watchdogs.
1. **PTT Soniox (готов):** PCM worklet, binary transport/output gate, partial UI,
   manual finalize, CommitArbiter, cancellation/browser tests.
2. **GigaAM local:** isolated preloaded worker/cache/setup/readiness, normalized
   final, manual debug provider switch.
3. **Automatic failover:** manager health/epoch/recovery, buffer/replay, all
   fault injection. Phases 0–3 = core hackathon MVP.
4. **VAD + pre-roll:** candidate lifecycle, acoustic metrics, reversible duck.
5. **Hands-free TI v1:** confirmed interrupt, semantic endpoint, echo window,
   basic backchannel/noise classification.
6. **Transcript intelligence:** stability, critical-token risk, corrections.
7. **Speculation:** PREPARE, then cancellable LLM prefill.
8. **Adaptive UX:** endpoint profiles, user pauses, avatar reactions.

PRs: `feat/stt-bench-contracts`, `feat/voice-input-ptt`,
`feat/gigaam-local-worker`, `feat/stt-failover`, `feat/voice-vad-candidates`,
`feat/turn-intelligence`. Каждый сохраняет text mode и cancellation regression.

## N. Files impact

Existing: contracts `events.py/session.py` и TS mirror; `TraineeSession`,
`useSessionSocket`, `cancelPlayback`, `AudioQueue`, mic hooks, composer/PTT/
indicator/consent, `TalkingHeadAvatar`; gateway `ws.py`, generation/pipeline/
session manager, DB models/repository/migration, config/speech client;
speech-service main/config/STT base/pyproject/Dockerfile; `.env.example`, compose,
Makefile, README.

New (имена уточняет PR 1): frontend PCM worklet/useVoiceCapture/output gate;
gateway `voice_turns.py`, `turn_intelligence.py`; speech STT WS/events/Soniox/
GigaAM/manager/buffer; `services/gigaam-worker/`; benchmark runner/manifest,
ADR и tests. Raw corpus audio не коммитится без consent/licensing решения.

## O. MVP vs Later

Core MVP: text+PTT в одной session, Soniox partial/final, canonical binary PCM,
local cancel/gate, gen/capture/epoch, atomic commit, GigaAM buffered failover,
bounded resources/readiness/fault injection/telemetry.

Later: hands-free candidate/VAD, echo/backchannel/stability/corrections,
speculation/adaptation, permanent audio evidence, diarization/translation.

## P. Risks

| Риск | Митигация |
|---|---|
| network/Soniox outage | buffer + GigaAM failover |
| rate/concurrency/cost | connection ADR, telemetry, bounded sessions |
| GigaAM CPU/cold start | 220M benchmark, isolated worker, preload, concurrency 1 |
| model download/demo | explicit setup, checksum, persistent cache/readiness |
| browser audio variance | worklet resampling/sample-count tests |
| echo/false endpoint | AEC + candidate duck + own acoustic corpus; PTT fallback |
| final/failure race | capture lock + epoch + DB idempotency |
| stale events | output gate + triple identity + sink fault tests |
| memory/input abuse | one capture, frame/sample/duration/backpressure limits |
| worker overload | bounded queue, typed error, text remains available |
| privacy | no permanent raw audio in MVP; minimized telemetry |

Soniox documents 100 realtime requests/min, 10 concurrent requests and max
300-minute stream; actual project/org limits are checked through API/Console.
Realtime sessions may terminate early and must be restartable; typed
`limit_exceeded`, internal and service-unavailable errors feed the centralized
failover policy. A paused persistent stream still needs keepalive and is billed
for its full duration, so per-turn vs persistent connection is a latency/cost
ADR after measurement, not a default architectural assumption.

## Потерянный ход: реплика персонажа

Failover не является потерей: буфер переигрывается в GigaAM целиком, поэтому
извиняться не за что, а фраза «я могла что-то не расслышать» была бы неправдой
и подтолкнула бы человека повторять сказанное — портя ту самую запись, которую
в этот момент расшифровывают. Пользователю сообщается только об исчезновении
партиалов (`voice_provider_switched`).

Ход считается потерянным в четырёх случаях: отказ обоих движков, обрыв потока
без терминального события, исключение на нашей стороне и пустой финал. Здесь
персонаж переспрашивает вслух своим голосом. `ErrorEvent` уходит в любом случае
— клиент по нему сбрасывает захват — но с `spoken=true`, и тогда баннер не
показывается: одна неудача не должна сообщаться дважды.

Аудио предрендерится (`make voice-recovery-setup`), потому что отказ TTS сам
входит в список причин потери хода. Ключ кеша — голос плюс текст.

Внешность и голос вынесены в реестр аватаров
(`scenario-service/app/avatars/registry.json`); сценарий ссылается на аватар
через `persona.avatar_id`. Голос и фраза наследуются от аватара, персона вправе
их перекрыть: одна модель может достаться разным характерам. Новый аватар —
одна запись в реестре, без правок кода. Реплика по умолчанию не содержит
прошедшего времени: род персонажа заранее неизвестен.

Филлер, закрывающий задержку GigaAM, сюда не относится и отклонён: он заговорил
бы поверх пайплайна и оставил бы лишний ход в стенограмме, если расшифровка
затем прошла успешно. Backchannels остаются в фазе 5.

## Q. Open questions

1. Minimum target CPU/RAM/OS for local fallback?
2. Maximum product duration of a spoken turn (dev guard is 20 s)?
3. Required Soniox data region/privacy constraints?
4. Required browser/device matrix beyond desktop Chrome?
5. Is permanent playable raw-audio evidence ever required, or is transcript +
   confidence sufficient?

## Local GigaAM readiness

- Separate internal `gigaam-worker` Docker profile/process; no paid service.
- Phase 0 compares v3 CTC/RNNT/e2e CTC/e2e RNNT, 220M first, PyTorch/ONNX;
  600M forbidden without measured benefit.
- ADR pins model/runtime/checksum. Env: `GIGAAM_MODEL`, `GIGAAM_RUNTIME`,
  `GIGAAM_CACHE_DIR`, CPU threads/concurrency.
- `make gigaam-setup` downloads/verifies ahead of demo; normal start is offline.
- Worker preloads/warms model before ready. Queue is bounded (MVP concurrency 1;
  queue limit from load test). Overload returns typed error, never blocks realtime.
- Direct PCM tensor path is benchmarked. Any file/ffmpeg workaround stays inside
  adapter and is rejected from hot path unless ADR proves it necessary.

## Definition of Done before implementation

Phase 0 ADR must fill only benchmark-dependent values: GigaAM model/runtime and
hardware baseline; Soniox connection/watchdogs/endpoint test config; final
capture/frame bounds; health/recovery policy; browser matrix; corpus quality
thresholds. Ownership, canonical format/resampling, atomic commit, races,
output gate, resource limits and PR boundaries are fixed above.

## Official sources

- [Soniox realtime](https://soniox.com/docs/stt/rt/real-time-transcription)
- [Soniox WebSocket](https://soniox.com/docs/api-reference/stt/websocket-api)
- [Soniox endpoint](https://soniox.com/docs/stt/rt/endpoint-detection)
- [Soniox manual finalization](https://soniox.com/docs/stt/rt/manual-finalization)
- [Soniox context](https://soniox.com/docs/stt/concepts/context)
- [Soniox confidence](https://soniox.com/docs/stt/concepts/confidence-scores)
- [Soniox timestamps](https://soniox.com/docs/stt/concepts/timestamps)
- [Soniox limits](https://soniox.com/docs/stt/rt/limits-and-quotas)
- [GigaAM official repository](https://github.com/salute-developers/GigaAM)
