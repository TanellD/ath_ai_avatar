# Задание Codex: обновить план Voice Input / Turn Intelligence

## Режим работы

У тебя уже есть подготовленный план голосового ввода и технический инвентарь `stt-phase.md`. Реализация ещё не начата.

**Сейчас не пиши код.** Сначала пересмотри существующий план с учётом требований ниже и выдай обновлённый, цельный, реализуемый план. Не переписывай всё с нуля без причины: сохрани удачные уже принятые решения, но исправь архитектуру там, где новые требования этого требуют.

После ревизии обнови соответствующие planning-документы проекта так, чтобы они стали единственным актуальным источником истины для реализации.

---

# 1. Контекст и цель

Мы делаем веб-прототип цифрового тренажёра с говорящим мультяшным нейроаватаром.

Пользователь должен иметь возможность:
- печатать реплики;
- позже — говорить голосом;
- перебивать аватара;
- продолжать один и тот же stateful диалог независимо от способа ввода.

После committed user turn дальнейший pipeline должен быть единым:

```text
CommittedUserTurn
    ↓
scenario/FSM/state
    ↓
dialogue agent / LLM
    ↓
streaming response
    ↓
TTS
    ↓
subtitles + avatar
```

Голосовой ввод не должен создавать второй независимый dialogue pipeline.

Наша цель — не просто подключить STT, а спроектировать собственный слой **Turn Intelligence**, который со временем сможет понимать:
- начало речи;
- продолжает ли пользователь мысль;
- вероятно ли завершение реплики;
- когда можно подготовить/запустить speculative processing;
- когда реплику можно окончательно commit;
- реальное ли это перебивание;
- backchannel ли это (`угу`, `ага`, `м-м`, `понятно`);
- шум/эхо ли это;
- произошла ли self-correction;
- насколько стабилен текущий partial transcript.

Для первого MVP не обязательно реализовывать всю продвинутую Turn Intelligence. Но архитектура первого среза не должна блокировать её добавление позже.

---

# 2. Критическое ограничение: независимая разработка

Архитектуру проектируем самостоятельно на основе:
- требований нашего продукта;
- текущего кода проекта;
- официальной документации используемых технологий;
- собственных benchmark и fault-injection тестов;
- общепринятых паттернов realtime/audio систем.

Не используй чужие проекты нейроаватаров/voice-agent систем как blueprint реализации.

Не копируй из внешних реализаций:
- структуру классов;
- state machines;
- thresholds;
- тайминги;
- эвристики;
- списки специальных слов;
- cancellation/barge-in алгоритмы.

Все наши thresholds и policy должны появиться из собственных измерений и быть зафиксированы в ADR после benchmark.

---

# 3. Что из существующего плана нужно сохранить

Если ревизия кода не обнаружит блокирующих причин, сохранить следующие решения.

## 3.1 Push-to-talk — первый вертикальный срез

Первую работающую версию голосового ввода делаем через PTT.

Для PTT пользовательское действие является явным намерением начать новую реплику, поэтому допустимо немедленно:
- остановить playback;
- начать новый capture;
- отменить старую генерацию;
- после отпускания/explicit end финализировать STT.

Hands-free добавляется после стабильной PTT-вертикали.

## 3.2 Gateway остаётся владельцем generation lifecycle

Существующий `gen_id` / generation lifecycle не переносить в STT provider.

STT не должен владеть dialogue generation.

Для явного PTT turn gateway создаёт новое поколение один раз. После получения final transcript повторный bump запрещён.

## 3.3 Аудио идёт через gateway → speech-service

Не передавать основной `SONIOX_API_KEY` в браузер.

Предпочтительный transport остаётся:

```text
browser
  ↓ binary audio
Gateway
  ↓ binary audio
speech-service
  ↓
STT provider
```

Не использовать JSON/base64 для realtime audio без веской причины.

## 3.4 Одна активная voice capture на сессию

Сохранить отдельный `capture_id` (либо предложить более удачное эквивалентное имя, если это действительно улучшает модель).

Late events старого capture не должны:
- менять UI;
- коммитить текст;
- запускать LLM;
- влиять на текущую генерацию.

## 3.5 В первой корректной версии LLM получает только committed/final transcript

Partial transcript сначала используется для:
- UI;
- telemetry;
- stability analysis;
- будущих оптимизаций.

Не выпускать TTS/user-visible LLM output по unstable partial в первом MVP.

Speculative LLM — отдельный этап после доказанной корректности cancellation/failover.

---

# 4. Primary STT: Soniox realtime

Primary provider — **Soniox realtime STT**.

Перед окончательным планом проверь актуальную официальную документацию, а не опирайся на старые предположения.

Проверить минимум:
- realtime WebSocket / streaming API;
- partial/non-final и final tokens;
- confidence;
- timestamps;
- semantic endpoint detection;
- manual finalization;
- context/terms для сценарной лексики;
- русский язык;
- reconnect/error semantics;
- rate limits;
- billing behaviour долгоживущего stream.

Официальные источники:
- https://soniox.com/docs/stt/rt/real-time-transcription
- https://soniox.com/docs/api-reference/stt/websocket-api
- https://soniox.com/docs/stt/rt/endpoint-detection
- https://soniox.com/docs/stt/rt/manual-finalization
- https://soniox.com/docs/stt/concepts/confidence-scores
- https://soniox.com/docs/stt/concepts/timestamps

Не привязывать Turn Intelligence напрямую к Soniox-specific objects.

---

# 5. Обязательный локальный fallback: GigaAM-v3

Cloud STT не может быть single point of failure.

Вместо Yandex/Deepgram как fallback использовать **локальный GigaAM-v3**, оптимизированный под русский язык.

Официальный репозиторий:
- https://github.com/salute-developers/GigaAM

GigaAM является open-source/MIT; актуальная линейка включает CTC/RNNT и end-to-end варианты, а официальный проект поддерживает локальный inference и ONNX export. Но конкретную модель/engine не выбирать вслепую — сначала benchmark на нашем железе.

## 5.1 Что исследовать для local fallback

Сравнить подходящие 220M варианты GigaAM-v3, в первую очередь варианты, реально пригодные для CPU fallback:
- CTC;
- RNNT;
- e2e CTC;
- e2e RNNT;
- PyTorch vs ONNX/ONNX Runtime, если оба варианта реально поддерживаемы текущей версией.

Не использовать 600M-модель, если benchmark не докажет, что она оправдана.

Benchmark должен включать:
- CPU-only latency;
- real-time factor;
- cold start;
- warm inference;
- RAM;
- размер весов;
- русский WER;
- имена;
- названия компаний/продуктов;
- суммы;
- проценты;
- даты;
- отрицания;
- спонтанную речь;
- шум;
- короткие реплики.

Отдельно проверить, можем ли мы подавать уже имеющийся PCM/audio buffer напрямую в inference path без временного файла и без ffmpeg в hot path. Если официальный high-level API этого не позволяет, изолировать преобразование внутри `GigaAmSttProvider`, не размазывая workaround по приложению.

## 5.2 Роль GigaAM

GigaAM — **degraded local fallback**, а не обязательная feature-parity копия Soniox.

При Soniox доступен FULL mode:

```text
VAD
+ streaming partials
+ confidence
+ timestamps
+ semantic endpoint
+ transcript stability
+ advanced Turn Intelligence
```

При отказе облака LOCAL DEGRADED mode может быть проще:

```text
VAD / explicit PTT end
+ buffered utterance
+ local GigaAM transcription
+ conservative endpoint policy
+ final transcript
```

В local mode допустимо:
- не иметь настоящих partial transcripts;
- не иметь semantic endpoint;
- не иметь confidence/timestamps либо иметь их только частично;
- отключить aggressive speculation;
- дольше ждать окончания реплики.

Но local mode обязан сохранить:
- возможность завершить тренировку;
- ровно один committed user turn;
- dialogue state;
- cancellation старого ответа;
- TTS;
- subtitles;
- avatar;
- итоговый отчёт.

---

# 6. Provider abstraction

Добавить provider abstraction в speech-service.

Не фиксировать интерфейс заранее, пока не изучен текущий код, но остальная система должна получать **нормализованные speech events**.

Концептуально:

```text
              ┌─ SonioxSttProvider
Audio ────────┤
              └─ GigaAmSttProvider
                     ↓
              normalized events
                     ↓
              Turn Intelligence
```

Нормализованные данные могут включать:

```text
capture_id
provider_epoch
provider
text
is_final
confidence?            // optional
start_ms?              // optional
end_ms?                // optional
semantic_endpoint?     // optional
```

Не заставлять fallback подделывать поля, которых он реально не умеет выдавать.

Полезно явно описать capabilities provider, например концептуально:

```text
supports_streaming_partials
supports_confidence
supports_token_timestamps
supports_semantic_endpoint
supports_context_terms
```

Turn Intelligence должен уметь корректно деградировать по capabilities.

---

# 7. STT provider manager и failover

Failover — отдельная часть архитектуры, а не набор `except` по проекту.

Предложить компонент вроде `SttProviderManager` / `SpeechRecognitionRouter` с ответственностью:
- primary selection;
- provider health;
- connection lifecycle;
- failover;
- recovery;
- provider epoch;
- telemetry.

Конкретное имя выбрать по conventions репозитория.

## 7.1 Когда primary считается непригодным

Спроектировать измеряемую policy для случаев:
- connect failure;
- authentication failure;
- WebSocket unexpectedly closed;
- rate limit;
- repeated provider errors;
- first-partial timeout;
- finalization timeout;
- аномально высокая latency.

Не назначать thresholds произвольно — предложить стартовые экспериментальные значения только как test configuration, затем зафиксировать их по benchmark.

---

# 8. Failover посреди пользовательской реплики

Это обязательный edge case.

Во время активного voice turn локально/на gateway или speech-service должен сохраняться **необработанный audio buffer текущей незакоммиченной реплики**.

Если Soniox падает в середине фразы:

```text
Soniox failure
    ↓
пометить provider epoch устаревшим
    ↓
не commit-ить partial Soniox
    ↓
активировать GigaAM
    ↓
передать GigaAM audio текущего utterance
    ↓
дождаться конца по PTT/VAD policy
    ↓
получить local final transcript
    ↓
commit ровно один раз
```

Нужно определить:
- где живёт rolling/current-turn buffer;
- максимальный размер;
- формат PCM;
- memory cost;
- момент очистки;
- поведение на длинной реплике;
- что происходит, если local fallback тоже завершился ошибкой.

Для PTT допустимо хранить аудио всего capture до commit — это упрощает первую реализацию.

---

# 9. Provider epoch и защита от поздних событий

`capture_id` защищает от старого пользовательского capture, но для failover нужна ещё identity конкретной provider-сессии.

Предложить модель вроде:

```text
session_id
capture_id
provider_epoch
```

Если после переключения на GigaAM приходит поздний Soniox partial/final:

```text
event.provider_epoch != active_provider_epoch
→ DROP
```

Никакое позднее событие старого provider не должно:
- перезаписать transcript;
- создать второй Turn;
- запустить LLM;
- изменить partial UI.

Acceptance invariant:

```text
lost committed voice turns = 0
duplicate committed voice turns = 0
```

---

# 10. Recovery обратно на Soniox

Не делать provider hopping внутри одного turn.

Если Soniox восстановился, пока текущая реплика уже обслуживается GigaAM:

```text
Turn N завершается на GigaAM

после Turn N:
health check confirms Soniox

Turn N+1 может снова использовать Soniox
```

Это уменьшает race conditions и делает lifecycle объяснимым.

---

# 11. Local GigaAM readiness и локальный запуск

Проект должен запускаться локально по инструкции команды, поэтому fallback должен быть реальным, а не теоретическим.

В плане определить:
- как устанавливается GigaAM runtime;
- как загружаются/кэшируются веса;
- где задаётся `GIGAAM_MODEL`;
- CPU-only baseline;
- нужен ли ONNX Runtime;
- pre-load / lazy-load policy;
- как отображается readiness;
- как избежать скачивания весов в момент демонстрации.

Для демо должен существовать заранее подготовленный local model cache либо явный setup step.

Не вводить новый платный сервис ради fallback.

---

# 12. PTT и hands-free должны иметь разную interruption policy

Это важная поправка к текущему плану.

## 12.1 Push-to-talk

Нажатие кнопки — сильный явный сигнал намерения пользователя.

Поэтому при PTT start можно сразу:
- `cancelPlayback()`;
- создать новый generation lifecycle;
- начать capture/STT.

Это остаётся первым MVP.

## 12.2 Hands-free

**Не делать необратимый cancel старой генерации на любой VAD onset.**

Причина: VAD может сработать на:
- echo голоса аватара;
- шум;
- backchannel пользователя;
- короткий неречевой звук.

Для hands-free нужен двухступенчатый путь:

```text
speech candidate
    ↓
быстрый LOCAL DUCK / PAUSE playback
    ↓
короткая проверка сигнала
    ↓
┌───────────────┬───────────────┬──────────────┐
real interrupt  backchannel     echo/noise
    ↓                ↓              ↓
CANCEL/NEW TURN   RESUME/continue   RESUME
```

Важно различать:
- reversible `duck/pause`;
- irreversible generation `cancel`.

На hands-free candidate start не bump-ить dialogue `gen_id` до подтверждённого interruption.

Предложить отдельные события/lifecycle для speech candidate и committed interruption.

---

# 13. Echo handling для будущего hands-free

Browser AEC включить, но не считать его достаточным.

Система знает:
- точный текст текущего ответа;
- audio playback timeline;
- какие speech chunks сейчас реально воспроизводятся.

Спроектировать возможность сравнивать candidate transcript не со всем ответом агента, а с **актуальным playback window** вокруг текущего времени.

Использовать сочетание:
- browser acoustic echo cancellation;
- playback reference;
- temporal overlap;
- transcript similarity;
- semantic evidence.

Конкретные similarity thresholds не брать извне — подобрать на собственном acoustic corpus.

Echo handling не обязателен для первого PTT PR, но extension point должен быть понятен заранее.

---

# 14. Backchannel vs interruption

В будущем hands-free режиме не считать любую человеческую речь перебиванием.

Нужно уметь различать как минимум:

```text
BACKCHANNEL
INTERRUPTION
UNKNOWN
```

Примеры backchannel в русском разговоре могут включать `угу`, `ага`, `м-м`, `понятно`, `да-да`, но не строить финальную систему только на hardcoded списке.

В первом приближении допустим гибрид:
- длительность;
- lexical/semantic class;
- положение относительно текущей речи агента;
- наличие нового вопроса/команды;
- confidence.

Backchannel может давать визуальную реакцию аватара, но не обязан останавливать речь.

Это post-MVP, но должно быть отражено в state machine Turn Intelligence.

---

# 15. Semantic endpoint и transcript stability

Для Soniox FULL mode использовать semantic endpointing, но не доверять одному сигналу без измерений.

Endpoint policy должна учитывать:
- VAD silence;
- semantic endpoint signal;
- stability partial transcript;
- confidence critical tokens;
- user speaking style позже.

## 15.1 Partial stability

Продумать измеримый алгоритм стабильности partial transcripts.

Например анализировать:
- longest stable prefix между соседними partials;
- churn последних токенов;
- время, которое prefix остаётся неизменным;
- confidence stable/unstable части.

Не фиксировать алгоритм по этому примеру — предложить лучший для фактического Soniox event model.

## 15.2 Critical semantic errors

WER недостаточен.

Отдельно учитывать ошибки в:
- отрицаниях;
- числах;
- датах;
- суммах;
- именах;
- scenario-critical entities.

Для будущей speculation учитывать комбинацию:

```text
semantic importance × recognition confidence × transcript stability
```

Не ограничиваться одним hardcoded списком слов.

---

# 16. Self-correction

В архитектуре различать:

```text
working transcript
committed user turn
```

Пример:

```text
«Мне нужно на пятницу… ой, нет, на субботу.»
```

Промежуточное `пятницу` не должно необратимо попасть в scenario/dialogue state.

В первый MVP достаточно commit только final transcript. Позже Turn Intelligence может распознавать corrections раньше, но committed state всегда должен оставаться транзакционно безопасным.

---

# 17. Speculative processing: только после корректности

Текущий план правильно не выпускает LLM/TTS до final в первой версии — сохранить это.

После стабильных cancellation/failover тестов спроектировать постепенную оптимизацию:

### Level A — PREPARE
Можно заранее:
- собрать context;
- подготовить scenario state;
- подготовить prompt/tool context.

Никакого user-visible output.

### Level B — LLM PREFILL / SPECULATE
Запустить LLM по достаточно стабильному partial, но не запускать TTS.

### Level C — SPEECH SPECULATION
Рассматривать только если собственные измерения покажут высокую надёжность endpoint/stability.

При продолжении речи speculative work должен безопасно отменяться.

Не включать Level C в обязательный MVP.

---

# 18. Telemetry

Существующие метрики сохранить и расширить.

Минимальные события:

```text
voice_capture_started
voice_capture_ended
vad_speech_candidate
stt_provider_selected
stt_connected
stt_first_partial
stt_partial
stt_final
stt_endpoint
stt_provider_error
stt_failover_started
stt_failover_completed
stt_provider_recovered
stt_audio_replay_started
stt_audio_replay_completed
turn_committed
playback_duck_started
playback_resumed
interruption_confirmed
old_generation_cancelled
```

Измерять минимум:
- Soniox first partial latency;
- end-of-speech → final latency;
- end-of-speech → first audio response;
- WER на размеченном корпусе;
- critical entity accuracy;
- lost/added negations;
- endpoint latency;
- false endpoint rate;
- late endpoint rate;
- partial stability/churn;
- acoustic onset → duck/silence latency;
- false barge-in rate;
- missed barge-in rate;
- resume success;
- Soniox availability;
- failover latency;
- failover success rate;
- GigaAM cold/warm latency;
- GigaAM RTF;
- GigaAM RAM/CPU;
- lost committed turns;
- duplicate committed turns;
- stale output count.

Hard acceptance из продукта:
- acoustic/user interruption → остановка речи не более 300 ms;
- конец речи → первый звук ответа не более 3 s;
- stale audio старой generation после cancellation = 0.

Внутренние цели можно поставить жёстче после baseline, но не придумывать их до замеров.

---

# 19. Fault injection — обязательная часть тестов

Добавить debug/fault-injection сценарий, который позволяет искусственно сломать Soniox.

Минимум проверить:

### Case A — primary недоступен до начала turn

```text
start voice turn
→ Soniox unavailable
→ GigaAM selected
→ turn recognized
→ exactly one commit
```

### Case B — Soniox падает посреди речи

```text
user starts speaking
→ Soniox получает часть audio
→ simulate failure
→ GigaAM activated
→ buffered utterance replayed/processed
→ user finishes
→ exactly one final transcript
→ dialogue continues
```

### Case C — late Soniox event после failover

```text
GigaAM already active
→ old Soniox final arrives
→ event dropped by provider epoch
```

### Case D — Soniox recovered

```text
current GigaAM turn finishes
→ recovery confirmed
→ next turn may use Soniox
```

### Case E — local fallback unavailable

Не падать целиком. Показать понятный voice error и оставить текстовый ввод полностью рабочим.

---

# 20. Не вводить лишнюю инфраструктуру в MVP

У проекта почти нет бюджета.

Не добавлять новый платный storage/service без обязательной необходимости.

Текущее предложение сохранять audio evidence в object storage пересмотреть:
- обязательные требования тренажёра не требуют хранения сырого пользовательского аудио;
- raw audio storage увеличивает privacy/consent/infra scope;
- для benchmark и debug можно хранить тестовые записи отдельно;
- production-like evidence storage вынести после core voice flow, если оно не требуется существующей бизнес-логике.

Если аудио evidence уже действительно используется текущим продуктом, предложить локальный/dev-compatible storage без новой платной зависимости.

Главный приоритет хакатона:

```text
reliable conversation
> resilience
> cancellation correctness
> latency
> advanced evidence storage
```

---

# 21. Предлагаемый порядок реализации после обновления плана

Проверь этот порядок относительно текущего кода и исправь при необходимости.

## Phase 0 — benchmark + contracts
- собственный русский corpus;
- Soniox benchmark;
- GigaAM local benchmark;
- provider capabilities;
- normalized STT events;
- fake providers;
- ADR выбора GigaAM runtime/model.

## Phase 1 — PTT Soniox vertical slice
- microphone;
- binary transport;
- Soniox provider;
- partial UI;
- final → existing `_run_turn` / единый dialogue pipeline;
- cancellation invariants.

## Phase 2 — GigaAM local provider
- local runtime;
- model cache/setup;
- same normalized final event;
- manual provider switch in debug.

## Phase 3 — automatic failover
- provider manager;
- provider epoch;
- current-turn audio buffer;
- mid-turn Soniox failure recovery;
- fault injection.

## Phase 4 — local VAD + pre-roll
- hands-free acoustic primitives;
- VAD metrics;
- no irreversible cancel on candidate onset.

## Phase 5 — hands-free Turn Intelligence v1
- candidate speech;
- duck/resume;
- semantic endpoint;
- confirmed interruption;
- echo/noise basic handling.

## Phase 6 — transcript intelligence
- partial stability;
- critical token confidence;
- self-correction model;
- backchannel classification.

## Phase 7 — speculation
- PREPARE;
- LLM prefill/speculation;
- only then consider speech speculation.

## Phase 8 — adaptive policy / advanced UX
- FAST/NORMAL/PATIENT endpoint profile;
- adaptation to user pause style;
- avatar reaction to listening/backchannels.

Не включать Phase 6–8 в обязательный хакатонный MVP, если они рискуют стабильностью core flow.

---

# 22. Что должно получиться от тебя сейчас

**Не реализовывай фичу.**

Сначала выдай ревизию существующего плана в формате:

## A. What stays
Какие решения текущего плана остаются без изменений и почему.

## B. What changes
Что нужно изменить из-за:
- обязательного GigaAM fallback;
- failover mid-turn;
- provider abstraction;
- различия PTT vs hands-free interruption;
- будущей Turn Intelligence.

## C. Current architecture fit
Какие реальные существующие компоненты/файлы проекта используются.

Не выдумывай пути файлов — сначала проверь репозиторий.

## D. Proposed architecture
Компоненты и ответственность каждого.

## E. Provider contract
Нормализованные события и capability model Soniox/GigaAM.

## F. Voice turn lifecycle
PTT lifecycle отдельно от hands-free candidate/interrupt lifecycle.

## G. Failover state machine
Soniox → GigaAM → recovery, включая mid-turn failure.

## H. Turn Intelligence state machine
Что нужно сейчас и какие extension points оставляем на потом.

## I. Cancellation model
Как `gen_id`, `capture_id` и provider epoch взаимодействуют и какие race conditions закрывают.

## J. Audio buffering
Где и сколько audio сохраняется до commit/failover.

## K. Metrics and telemetry
События, timestamp points и формулы ключевых метрик.

## L. Testing and fault injection
Unit / contract / integration / browser / acoustic / failover tests.

## M. Implementation phases and PRs
Маленькие проверяемые PR, каждый оставляет текстовый режим рабочим.

## N. Files impact
Какие существующие файлы меняются, какие новые создаются.

## O. MVP vs Later
Жёстко разделить обязательное и исследовательское.

## P. Risks
Минимум:
- network;
- Soniox outage;
- GigaAM CPU performance;
- model loading;
- browser audio;
- echo;
- false endpoints;
- race conditions;
- stale events;
- memory/audio buffer;
- packaging/local setup;
- API cost.

## Q. Open questions
Только реально блокирующие вопросы, на которые нельзя ответить изучением текущего кода или официальной документации.

---

# 23. Definition of Done для самого плана

План готов только если из него однозначно понятно:

1. Как PTT работает end-to-end.
2. Как Soniox является primary, но не single point of failure.
3. Как GigaAM работает локально без облачного API.
4. Что происходит при падении Soniox посреди фразы.
5. Почему реплика не теряется и не commit-ится дважды.
6. Почему late Soniox events после failover безвредны.
7. Как current text input остаётся рабочим всегда.
8. Почему hands-free не убивает ответ агента на каждый ложный VAD onset.
9. Как архитектура позволит позже добавить backchannels, semantic endpoint, stability и speculation без переписывания core pipeline.
10. Какие части реально входят в хакатонный MVP.
11. Как всё запускается локально, включая GigaAM weights/runtime.
12. Как fault injection доказывает resilience вживую.

Главный архитектурный принцип:

```text
                    ┌──────── Soniox realtime STT
Microphone → audio ─┤
                    └──────── local GigaAM fallback
                                ↓
                       Normalized Speech Events
                                ↓
                         Turn Intelligence
                                ↓
                         CommittedUserTurn
                                ↓
                       existing dialogue flow
```

**Soniox — realtime primary.**

**GigaAM — local resilience layer для русского языка.**

**Turn Intelligence — наша собственная архитектура принятия решений.**

**Text input остаётся независимым гарантированным способом пройти тренировку.**

---

# 24. Дополнительные edge cases, обязательные к учёту перед реализацией

Эти пункты не меняют базовую архитектуру, но должны быть явно закрыты в обновлённом плане.

## 24.1 Канонический audio format и resampling

Браузерный микрофон не гарантирует нужный STT sample rate. На практике MediaStream часто работает в 48 kHz, тогда как локальный ASR может ожидать другой формат.

Нужно определить один внутренний канонический формат audio transport, например концептуально:

```text
mono
PCM
fixed sample rate
fixed sample format
```

Конкретный sample rate/sample format выбрать после проверки Soniox и GigaAM API.

План должен однозначно определить:
- где выполняется resampling;
- кто отвечает за mono conversion;
- не происходит ли двойной resampling;
- как считаются timestamps — предпочтительно от количества audio samples, а не от wall-clock `Date.now()`;
- что происходит при несовпадении реального device sample rate и ожидаемого;
- как тестируется drift на длинной реплике.

Один и тот же buffered utterance должен быть пригоден для replay в GigaAM после failover без повторного lossy encode/decode.

## 24.2 Local inference не должен блокировать realtime event loop

GigaAM CPU inference потенциально тяжёлый.

Нельзя запускать тяжёлый local inference так, чтобы он блокировал:
- gateway WebSocket loop;
- приём новых audio frames;
- cancellation;
- heartbeat;
- TTS/другие realtime events.

Codex должен определить execution model:
- отдельный worker process;
- bounded executor;
- либо другой изолированный inference worker.

Обязательно определить:
- queue/backpressure policy;
- maximum concurrent local STT jobs;
- cancellation старого local inference;
- CPU thread limits;
- поведение при перегрузке CPU.

Для хакатонного MVP приоритет — предсказуемая отзывчивость приложения, даже если local STT работает медленнее Soniox.

## 24.3 Exactly-once commit должен быть атомарным

`capture_id` и `provider_epoch` защищают от late events, но сами по себе не доказывают exactly-once commit.

Нужен единый commit arbiter / atomic state transition для voice capture, концептуально:

```text
CAPTURING
→ FINALIZING
→ COMMITTED
```

или

```text
CAPTURING
→ ABORTED
```

Переход в `COMMITTED` должен происходить только один раз для конкретного `capture_id`.

Повторный final, reconnect replay, late provider event или повторная доставка WebSocket-события должны быть idempotent.

Codex должен показать, где именно находится эта гарантия: gateway/session state/DB transaction/compare-and-set либо эквивалент текущей архитектуры.

## 24.4 Гонка: provider final и provider failure почти одновременно

Отдельно закрыть сценарии:

### A
Soniox успел отдать валидный final → затем socket закрылся.

Если final уже принят commit arbiter, GigaAM fallback НЕ должен создавать второй transcript.

### B
Socket упал после endpoint candidate, но до authoritative final/commit.

Тогда допустим replay buffered audio через GigaAM.

### C
GigaAM уже начал fallback, а Soniox late final пришёл позже.

Победитель определяется provider epoch + commit state; поздний final отбрасывается.

Failover state machine должна явно описывать эти границы.

## 24.5 Browser capture lifecycle: потерянный end event

PTT нельзя строить только на идеальном `pointerdown → pointerup`.

Нужно обработать минимум:
- `pointercancel`;
- lost pointer capture;
- отпускание кнопки вне элемента;
- уход вкладки в background / `visibilitychange`;
- закрытие/refresh страницы;
- потерю WebSocket;
- отключение микрофона;
- permission revoked;
- device unplugged;
- слишком длинное удержание PTT;
- capture, в котором речи не было.

Должны существовать:
- max capture duration;
- abort/finalize watchdog;
- безопасная очистка audio buffer;
- понятный возврат в idle state.

Никакой потерянный browser event не должен оставлять session навсегда в `CAPTURING`.

## 24.6 Provider stall != provider disconnect

Primary может зависнуть, не закрывая WebSocket.

Health policy должна различать:
- socket closed;
- connection alive, но нет ожидаемого STT progress;
- audio отправляется, но partial/final не приходит;
- finalize отправлен, но authoritative final не приходит;
- provider отвечает error/control events.

Использовать watchdog по реальному progress, а не только `on_close`.

Для Soniox отдельно проверить актуальные keepalive/idle timeout rules и стоимость persistent stream. Решение `persistent connection vs per-turn connection` принять по собственным latency/cost замерам и зафиксировать в ADR.

## 24.7 Local playback suppression до server ACK

При PTT пользователь должен услышать мгновенное прекращение старого ответа локально.

Но возможна гонка:

```text
browser cancelPlayback()
↓
speech_start отправлен
↓
сеть оборвалась ДО gateway ACK
↓
backend всё ещё генерирует старый ответ
```

Frontend не должен снова начать воспроизводить старые arriving chunks только потому, что server ещё не успел создать новый `gen_id`.

Нужен локальный input/capture gate:
- пока новый user capture активен/pending, user-visible output предыдущего dialogue generation подавляется;
- после gateway ACK состояние связывается с authoritative generation lifecycle;
- при failure пользователь получает понятный voice error и может продолжить текстом.

Codex должен встроить это в cancellation model и тесты сетевых гонок.

## 24.8 Проверить все user-visible sinks на stale output

Инвариант cancellation относится не только к audio.

После отмены старой generation не должны оживать:
- audio chunks;
- TTS queue;
- subtitles;
- avatar lip-sync;
- facial animation;
- semantic gestures/motion markers;
- delayed timers/callbacks старой реплики.

Codex должен сделать инвентарь всех user-visible sinks текущего проекта и указать, где проверяется актуальность generation/capture.

Acceptance test: искусственно задержать старое событие каждого типа и убедиться, что после нового turn оно не становится видимым/слышимым.

## 24.9 Ограничения transport и input safety

Даже для локального прототипа gateway должен валидировать:
- принадлежность `capture_id` текущей session;
- допустимый порядок `speech_start → audio → speech_end`;
- максимальный размер binary frame;
- максимальный размер/длительность capture;
- количество одновременных capture;
- некорректный sample rate/channels/format.

Ошибочный клиент не должен бесконечно накапливать audio buffer или создавать неограниченные local inference jobs.

## 24.10 Provenance / clean-room discipline

Чтобы архитектура была явно независимой от чужих нейроаватарных реализаций:

- не добавлять в planning docs ссылки на чужие avatar/voice-agent repositories как источник архитектуры;
- для каждого нетривиального решения указывать источник основания: product requirement, текущий код, официальная документация provider/runtime либо собственный benchmark;
- thresholds/timers фиксировать только после собственных измерений;
- не переносить чужие имена классов, state machine, списки эвристик или последовательности состояний;
- ADR должен объяснять решение из наших требований и результатов тестов.

Совпадение общих инженерных паттернов (VAD, buffering, cancellation tokens/epochs, idempotency, provider abstraction, backpressure) само по себе не является копированием конкретной реализации; важно, чтобы конкретная архитектура и параметры были выведены и проверены самостоятельно.

---

# 25. Дополнение к Definition of Done плана

Кроме пунктов выше, план считается готовым только если однозначно отвечает:

13. Какой канонический audio format используется end-to-end и где выполняется resampling.
14. Почему local GigaAM inference не блокирует realtime loops.
15. Где находится атомарная exactly-once гарантия commit user turn.
16. Что происходит при гонке `Soniox final` ↔ `Soniox disconnect`.
17. Что происходит, если браузер не прислал обычный `speech_end`.
18. Как определяется provider stall без фактического disconnect.
19. Почему frontend не возобновит старый output, если PTT уже начался, а `speech_start` ещё не подтверждён gateway.
20. Как stale-event protection распространяется на audio, subtitles, lip-sync, face/body animation и gestures.
21. Как realtime transport защищён от бесконечного capture/buffer/inference overload.
22. Какими собственными измерениями/официальными источниками обоснованы ключевые policy и thresholds.
