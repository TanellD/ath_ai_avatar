# Фаза `[STT]`: технический инвентарь

Статус: текстовый ввод сохранён; первый toggle-to-talk PTT/Soniox vertical slice реализован и
ожидает ручной проверки микрофона в браузере. Единственный актуальный план —
[`voice-input-plan.md`](voice-input-plan.md); этот файл фиксирует только
подготовленные места и не вводит альтернативных решений.

## Уже подготовлено

- Контракты: voice lifecycle events и `TranscriptEvent` в
  `packages/contracts/ath_contracts/events.py`, TS mirror, поля
  `Turn.stt_confidence/audio_ref`.
- Frontend: AudioWorklet capture/resampling, binary WS, `cancelPlayback.ts`,
  `listening/recognizing`, PTT UI и partial transcript.
- Gateway: `GenerationRegistry`, voice capture registry, один `gen_id`,
  exactly-once commit по `(session_id, capture_id)` и единый `TurnPipeline`.
- Speech-service: provider-neutral STT contract, bounded PCM buffer, mock,
  realtime Soniox adapter и `/stt/stream`.

## Важные поправки к старым заготовкам

- Закомментированные events нельзя просто включить: нужны `capture_id`, binary
  transport, provider epoch и start ACK.
- VAD-комментарий про cancel на onset устарел для hands-free. Сразу cancel
  делает только PTT; hands-free сначала candidate + reversible duck.
- `speech_start` не может вызвать текущий `handle_user_message(text)`: текста
  ещё нет. Final voice text входит в общий pipeline без второго `gen_id` bump.
- Текущий STT interface требует искусственную confidence; GigaAM degraded
  metadata должна быть optional.
- Raw audio storage/MinIO не требуется core flow. До commit хранится только
  bounded in-memory buffer для failover, затем удаляется.

## Не реализовано

Полный corpus/benchmark и ADR параметров, GigaAM worker/cache, provider
manager/failover/replay, hands-free candidate/duck/echo policy и полный
fault-injection/browser harness.

Текстовый `UserMessage`, FSM, `GenerationRegistry`, `AudioQueue`, TalkingHead/
HeadAudio и TTS сохраняются; Redis/Postgres не добавляются только ради STT.
