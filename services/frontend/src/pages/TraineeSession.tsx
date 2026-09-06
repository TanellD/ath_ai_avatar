/**
 * Экран сотрудника — Claude.md §8.
 *
 * Здесь сходятся все инварианты клиента, поэтому читать этот файл стоит вместе
 * с §6:
 *
 *   - поколение (`genRef`) — источник истины для фильтрации событий;
 *   - отправка реплики вызывает cancelPlayback() ДО отправки в сокет;
 *   - аудио-чанки идут только через AudioQueue, который сам отбрасывает чужие;
 *   - субтитры, панель истории и индикатор состояния читают время у
 *     PlaybackClock / реальное завершение воспроизведения у AudioQueue,
 *     и больше нигде.
 *
 * `AudioContext` теперь создаёт и владеет им TalkingHeadAvatar (это его
 * `head.audioCtx`), а не этот компонент: PlaybackClock и AudioQueue
 * собираются только после того, как аватар отдаст готовый контекст через
 * onReady — до этого момента отправка реплики недоступна (см. MessageComposer
 * disabled), так же как в проверенном PoC send оставался disabled, пока
 * аватар не загрузился.
 *
 * Вёрстка — по макету front/Экран сотрудника.dc.html. Прогресс по этапам
 * («Этап X из Y») в макете статичен — здесь он настоящий: сценарий
 * подгружается отдельным запросом (scenarioApi.get), а текущий этап —
 * это stage_id из последнего ActionEvent (§5, конечный автомат решает код,
 * не клиент — клиент только отображает то, что код уже решил). Переключатель
 * персонажа из макета не воспроизведён: смена персонажа сценарием backend'ом
 * не поддержана, рисовать нерабочую кнопку — не вариант.
 *
 * [STT] Голосовой ввод живёт здесь же и НЕ заменяет текстовый: чекбокс
 * включает кнопку записи, композер остаётся на месте и блокируется только
 * на время активной записи. Оба пути идут через один и тот же протокол
 * перебивания (§6) — cancelPlayback локально, потом новое поколение.
 * Захват микрофона, детектор паузы и таймер молчания вынесены в
 * audio/mic/* и session/SilenceFollowup — здесь только их связывание.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { gatewayApi, scenarioApi } from '@/api/client';
import { AudioQueue } from '@/audio/AudioQueue';
import { PlaybackClock } from '@/audio/PlaybackClock';
import { cancelPlayback } from '@/audio/cancelPlayback';
import { DEFAULT_PAUSE_DETECTOR_CONFIG, PauseDetector } from '@/audio/mic/PauseDetector';
import { useMicCapture } from '@/audio/mic/useMicCapture';
import {
  AVATAR_MODELS,
  TalkingHeadAvatar,
  type AvatarModelConfig,
  type AvatarPlaybackHandle,
} from '@/avatar/TalkingHeadAvatar';
import { ChatPanel, type ChatTurn } from '@/components/ChatPanel';
import { MessageComposer } from '@/components/MessageComposer';
import { PlaybackIndicator, type PlaybackState } from '@/components/PlaybackIndicator';
import { PushToTalkToggle } from '@/components/PushToTalkToggle';
import { SessionEndOverlay } from '@/components/SessionEndOverlay';
import { SessionStartOverlay } from '@/components/SessionStartOverlay';
import { StageHint } from '@/components/StageHint';
import type { Scenario, ServerEvent, SubtitleEvent } from '@/contracts/events';
import { appendAgentToken } from '@/session/agentLines';
import { SilenceFollowup, type SilencePhase } from '@/session/SilenceFollowup';
import { Subtitles } from '@/subtitles/Subtitles';
import type { SessionError } from '@/types/errors';
import { useSessionSocket } from '@/ws/useSessionSocket';

interface AudioRig {
  audioCtx: AudioContext;
  clock: PlaybackClock;
  queue: AudioQueue;
  resetFace: () => void;
  setEmotion: AvatarPlaybackHandle['setEmotion'];
}

interface VoiceTimingMarks {
  captureId: string;
  genId: number;
  captureStartedAt: number;
  speechEndedAt?: number;
  firstPartialRecorded: boolean;
  responseAudioRecorded: boolean;
}

interface VoiceMetrics {
  stopMs?: number;
  ackMs?: number;
  firstPartialMs?: number;
  finalizationMs?: number;
  responseTtfaMs?: number;
}

export function TraineeSession() {
  const { scenarioId = '' } = useParams();

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [error, setError] = useState<SessionError | null>(null);
  const [transcript, setTranscript] = useState<ChatTurn[]>([]);
  const [cues, setCues] = useState<SubtitleEvent[]>([]);
  const [subtitlesFrozen, setSubtitlesFrozen] = useState(false);
  const [pushToTalk, setPushToTalk] = useState(false);
  const [voiceActive, setVoiceActive] = useState(false);
  const [voiceDraft, setVoiceDraft] = useState('');
  // Распознавание ушло на резервный движок без партиалов: черновик больше
  // не обновляется, и это надо объяснить, а не оставлять экран замершим.
  const [voiceBuffered, setVoiceBuffered] = useState(false);
  const [voiceMetrics, setVoiceMetrics] = useState<VoiceMetrics | null>(null);
  const [playback, setPlayback] = useState<PlaybackState>('disconnected');
  const [audio, setAudio] = useState<AudioRig | null>(null);
  /**
   * Пока false — сокет не открыт, и персонаж молчит. Разделение нужно из-за
   * автоплея: агент говорит первым (§1), а звук в браузере не пойдёт, пока
   * пользователь не совершит жест. См. SessionStartOverlay.
   */
  const [started, setStarted] = useState(false);
  /** Тренировка окончена — по кнопке сотрудника или по решению автомата (§3). */
  const [finished, setFinished] = useState(false);
  const [avatarModel, setAvatarModel] = useState<AvatarModelConfig>(AVATAR_MODELS.aith);
  // Только для шапки (заголовок, прогресс по этапам) — не участвует ни в
  // одном инварианте отмены/поколений, поэтому обычный useState, не ref.
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [currentStageId, setCurrentStageId] = useState<string | null>(null);

  /**
   * Текущее поколение. Именно ref, а не useState: значение читается в
   * обработчике сокета синхронно, и устаревшее замыкание здесь означало бы
   * пропущенный отброс чанка — то есть нарушение метрики 4.
   */
  const genRef = useRef(0);
  const emotionGenerationRef = useRef<number | null>(null);
  /**
   * Поколение, к реплике которого сейчас дописываются токены. Без него
   * инициативная реплика по молчанию приклеивалась к ПРЕДЫДУЩЕМУ ответу
   * персонажа: до неё два ответа подряд всегда разделяла реплика
   * пользователя, и «последняя строка агента» однозначно означала «та же
   * самая реплика». Теперь это больше не так.
   */
  const agentLineGenRef = useRef<number | null>(null);
  const activeCaptureRef = useRef<string | null>(null);
  const captureEndingRef = useRef(false);
  const voiceTimingRef = useRef<VoiceTimingMarks | null>(null);
  const pauseDetectorRef = useRef(new PauseDetector());
  const voiceEndRef = useRef<() => void>(() => undefined);
  const silenceTimeoutRef = useRef<(phase: SilencePhase) => void>(() => undefined);
  const silenceFollowupRef = useRef<SilenceFollowup | null>(null);
  if (silenceFollowupRef.current === null) {
    silenceFollowupRef.current = new SilenceFollowup((phase) => silenceTimeoutRef.current(phase));
  }

  useEffect(() => () => silenceFollowupRef.current?.stop(), []);

  const handleAvatarReady = useCallback((handle: AvatarPlaybackHandle) => {
    const clock = new PlaybackClock(handle.audioCtx);
    // Четвёртый параметр — onIdle: единственный правильный источник для
    // индикатора «персонаж говорит». `action` от сервера приходит, когда
    // байты уже ОТПРАВЛЕНЫ, а не когда они доиграли — раньше индикатор либо
    // не гас вовсе (обычный переход stay/next_stage не трогал playback), либо
    // гас слишком рано. Теперь состояние идёт от факта тишины в колонках.
    const queue = new AudioQueue(
      handle.audioCtx,
      clock,
      handle.destination,
      (reason) => {
        setPlayback('idle');
        if (reason === 'ended') silenceFollowupRef.current?.resume();
      },
      (genId, leadMs) => {
        const timing = voiceTimingRef.current;
        if (
          !timing?.speechEndedAt
          || timing.genId !== genId
          || timing.responseAudioRecorded
        ) return;
        timing.responseAudioRecorded = true;
        const responseTtfaMs = Math.round(performance.now() + leadMs - timing.speechEndedAt);
        setVoiceMetrics((current) => ({ ...current, responseTtfaMs }));
        console.info('[voice-metric]', {
          capture_id: timing.captureId,
          response_ttfa_ms: responseTtfaMs,
        });
      },
    );
    // Оба поля обязательны: audioCtx нужен, чтобы разблокировать автоплей по
    // клику «Начать» (агент говорит первым), setEmotion — чтобы лицо
    // отыгрывало эмоцию реплики.
    setAudio({
      audioCtx: handle.audioCtx,
      clock,
      queue,
      resetFace: handle.resetFace,
      setEmotion: handle.setEmotion,
    });
  }, []);

  const handleAvatarError = useCallback((message: string) => {
    setError({ type: 'audio', message: 'Не удалось загрузить аватара', details: message });
  }, []);

  // Сессия заводится по нажатию «Начать», а не на монтировании страницы —
  // см. handleStart. Раньше строка в БД появлялась на каждый заход, и список
  // тренировок у методиста состоял в основном из пустышек.

  // Персонаж и этапы — только для отображения в шапке. Ошибку здесь не
  // считаем фатальной (сессия и без неё работает), поэтому молча пропускаем.
  useEffect(() => {
    let cancelled = false;
    scenarioApi
      .get(scenarioId)
      .then((data) => {
        if (!cancelled) setScenario(data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [scenarioId]);

  // AudioContext больше не наш: им владеет TalkingHeadAvatar (head.audioCtx),
  // закрывать его здесь при размонтировании было бы вмешательством в чужой
  // жизненный цикл. См. докстринг TalkingHeadAvatar.tsx про best-effort cleanup.

  // -------------------------------------------------------------- события WS

  const handleEvent = useCallback(
    (event: ServerEvent) => {
      switch (event.type) {
        case 'token': {
          silenceFollowupRef.current?.pause();
          setPlayback('speaking');
          // Токен продолжает текущую реплику, только если он из того же
          // поколения. Иначе это новый ответ персонажа — ему нужен свой
          // пузырь, даже если предыдущая строка тоже принадлежит персонажу.
          const continues = agentLineGenRef.current === event.gen_id;
          agentLineGenRef.current = event.gen_id;
          setTranscript((lines) => appendAgentToken(lines, event.text, continues));
          break;
        }

        case 'audio_chunk':
          // Аватар мог ещё не догрузиться (13 МБ GLB) к моменту первого
          // чанка — тогда его попросту некуда проигрывать. Очередь также сама
          // сверит gen_id ещё раз — намеренное дублирование проверки: чанк
          // мог быть декодирован уже после перебивания.
          if (audio) {
            if (emotionGenerationRef.current !== event.gen_id) {
              audio.setEmotion(event.emotion);
              emotionGenerationRef.current = event.gen_id;
            }
            void audio.queue.enqueue({ genId: event.gen_id, seq: event.seq, data: event.data });
          }
          break;

        case 'subtitle':
          setCues((current) => [...current, event]);
          break;

        case 'action':
          // finish — конец тренировки. Приходит сразу, отчёт готовится уже
          // после него и сотруднику не показывается (см. SessionEndOverlay).
          if (event.action === 'finish') {
            silenceFollowupRef.current?.stop();
            audio?.queue.stopAll();
            setPlayback('idle');
            setFinished(true);
            break;
          }
          // Обычный переход (stay/next_stage) не обязан гасить индикатор —
          // это делает AudioQueue.onIdle, когда реплика реально доиграет.
          // Исключение — предохранитель: если очередь и так уже пуста
          // (ответ пришёл вовсе без звука, например при ошибке TTS),
          // action — единственный сигнал, что ход завершён.
          if (audio?.queue.isIdle) {
            setPlayback('idle');
            silenceFollowupRef.current?.resume();
          }
          // Только для прогресса в шапке — сам переход уже сделал сервер.
          setCurrentStageId(event.stage_id);
          break;

        case 'cancel':
          // Сервер подтвердил отмену. Локально мы её уже выполнили — это
          // подстраховка для случая, когда отмену инициировал не клиент.
          if (audio && event.gen_id !== genRef.current) audio.queue.stopAll();
          break;

        case 'speech_started':
          if (voiceTimingRef.current?.captureId === event.capture_id) {
            const ackMs = Math.round(performance.now() - voiceTimingRef.current.captureStartedAt);
            setVoiceMetrics((current) => ({ ...current, ackMs }));
          }
          if (!captureEndingRef.current) setPlayback('listening');
          break;

        case 'voice_provider_switched':
          if (!event.partials_available && activeCaptureRef.current === event.capture_id) {
            // Замерший черновик читается как «меня перестали слышать», и человек
            // начинает повторять — портит ту самую запись, которую сейчас
            // расшифровывают. Убираем его и объясняем паузу.
            setVoiceDraft('');
            setVoiceBuffered(true);
          }
          break;

        case 'transcript':
          if (
            !event.is_final
            && voiceTimingRef.current?.captureId === event.capture_id
            && !voiceTimingRef.current.firstPartialRecorded
          ) {
            voiceTimingRef.current.firstPartialRecorded = true;
            const firstPartialMs = Math.round(
              performance.now() - voiceTimingRef.current.captureStartedAt,
            );
            setVoiceMetrics((current) => ({ ...current, firstPartialMs }));
          }
          setVoiceDraft(event.is_final ? '' : event.text);
          if (event.is_final) {
            const timing = voiceTimingRef.current;
            if (timing?.captureId === event.capture_id && timing.speechEndedAt) {
              const finalizationMs = Math.round(performance.now() - timing.speechEndedAt);
              setVoiceMetrics((current) => ({ ...current, finalizationMs }));
              console.info('[voice-metric]', {
                capture_id: timing.captureId,
                finalization_ms: finalizationMs,
              });
            }
            activeCaptureRef.current = null;
            captureEndingRef.current = false;
            setVoiceActive(false);
            setVoiceBuffered(false);
            if (event.text.trim()) {
              setTranscript((lines) => [...lines, { role: 'user', text: event.text.trim() }]);
              setPlayback('thinking');
            } else {
              setPlayback('idle');
              silenceFollowupRef.current?.resume();
              setError({ type: 'audio', message: 'Речь не распознана, попробуйте ещё раз' });
            }
          }
          break;

        case 'report':
          // Отчёт сотруднику намеренно не показывается: это экран методиста
          // (§2), и он уже сохранён на сервере — здесь ловить нечего. Оверлей
          // конца тренировки поднят раньше, по action: finish.
          setPlayback('idle');
          silenceFollowupRef.current?.stop();
          break;

        case 'error':
          // Совместимость со старым gateway: запоздалый MediaStream frame
          // после speech_end — штатная гонка и не должен становиться баннером.
          if (event.code === 'unexpected_audio') break;
          if (event.code.startsWith('stt_') || event.code.includes('voice_capture')) {
            activeCaptureRef.current = null;
            captureEndingRef.current = false;
            setVoiceActive(false);
            setVoiceBuffered(false);
          }
          if (
            event.code === 'silence_followup_failed'
            || event.code === 'turn_failed'
            || event.code === 'opening_failed'
          ) {
            // Все три реплики персонажа без предшествующего audio_chunk не
            // дают клиенту ни одной другой точки восстановления: ActionEvent
            // для них не шлётся, а AudioQueue.onIdle не сработает без единого
            // сыгранного чанка. Эта ошибка — единственный сигнал, что ход
            // мёртв. Без явного возврата в idle индикатор завис бы навсегда,
            // а таймер молчания, не получив resume(), замолчал бы до конца
            // сессии — даже если сотрудник ведёт себя как обычно.
            setPlayback('idle');
            silenceFollowupRef.current?.resume();
          }
          // Персонаж уже переспросил вслух — красный баннер поверх этого
          // сообщил бы об одной неудаче дважды и вывел бы собеседника из роли.
          if (!event.spoken) {
            setError({ type: 'server', message: event.message, details: event.code });
          }
          break;

        default:
          break;
      }
    },
    [audio],
  );

  /**
   * Подтянуть поколение сервера. Свой счётчик клиент ведёт зеркально, но
   * после переподключения он остаётся на своём значении, а сервер продолжает
   * с сохранённого — и тогда фильтр по gen_id отбросил бы вообще всё.
   */
  const syncGeneration = useCallback(async (id: string) => {
    try {
      const { current_gen: currentGen } = await gatewayApi.getSession(id);
      genRef.current = currentGen;
      audio?.queue.startGeneration(currentGen);
    } catch (cause) {
      setError({
        type: 'server',
        message: 'Не удалось восстановить состояние сессии',
        details: cause instanceof Error ? cause.message : String(cause),
      });
    }
  }, [audio]);

  // Сокет открывается только после клика: сервер, увидев подключение, сразу
  // начинает открывающую реплику (gateway/app/api/ws.py), и генерировать её
  // в звук, который браузер откажется играть, — значит выбросить её впустую.
  const {
    state: connection,
    send,
    sendUserMessage,
    sendSpeechStart,
    sendSpeechEnd,
    sendSpeechAbort,
    sendSilenceTimeout,
    sendAudio,
  } = useSessionSocket({
    sessionId: started ? sessionId : null,
    onEvent: handleEvent,
    currentGeneration: () => genRef.current,
    onError: setError,
    onReconnect: () => {
      // Незавершённая реплика умерла вместе со старым сокетом: продолжать
      // с середины нечего, поэтому возвращаемся в покой и берём поколение
      // у сервера заново.
      audio?.queue.stopAll();
      activeCaptureRef.current = null;
      captureEndingRef.current = false;
      setVoiceActive(false);
      setVoiceDraft('');
      setVoiceBuffered(false);
      setCues([]);
      setSubtitlesFrozen(false);
      setPlayback('idle');
      silenceFollowupRef.current?.resume();
      if (sessionId) void syncGeneration(sessionId);
    },
  });

  silenceTimeoutRef.current = (phase) => {
    if (connection !== 'open' || !audio || finished || activeCaptureRef.current) return;
    sendSilenceTimeout(phase, avatarModel.id);
    genRef.current += 1;
    audio.queue.startGeneration(genRef.current);
    setCues([]);
    setSubtitlesFrozen(false);
    setPlayback('thinking');
  };

  const { start: startMic, stop: stopMic, level: micLevel } = useMicCapture({
    onFrame: (frame) => {
      if (!activeCaptureRef.current || captureEndingRef.current) return;
      sendAudio(frame);
      if (pauseDetectorRef.current.push(frame)) {
        console.info('[voice-metric]', {
          event: 'client_pause_endpoint',
          silence_ms: DEFAULT_PAUSE_DETECTOR_CONFIG.endpointSilenceMs,
        });
        voiceEndRef.current();
      }
    },
    onError: (message) => {
      setError({ type: 'audio', message });
    },
  });

  // Оверлей поднимает не эта функция, а ответное `action: finish` от сервера:
  // завершает сессию он, и локально угадывать этот момент незачем.
  const handleFinish = useCallback(() => {
    silenceFollowupRef.current?.stop();
    send({ type: 'finish_session' });
  }, [send]);

  const handleStart = useCallback(() => {
    if (!audio) return;

    // Разблокировка автоплея обязана произойти внутри обработчика клика:
    // отложенный resume() браузер уже не засчитает как жест пользователя.
    // Именно поэтому создание сессии ниже идёт ПОСЛЕ resume(), а не до: между
    // кликом и await'ом жест ещё «свежий», после — уже нет.
    void audio.audioCtx.resume().catch((cause: Error) => {
      setError({
        type: 'audio',
        message: 'Не удалось включить звук',
        details: cause.message,
      });
    });

    // Персонаж заговорит сам, как только сервер увидит подключение, — своё
    // поколение он заведёт первым же bump(), поэтому локально ждём gen 1.
    genRef.current = 1;
    audio.queue.startGeneration(genRef.current);
    setPlayback('thinking');

    gatewayApi
      .createSession(scenarioId)
      .then((response) => {
        setSessionId(response.session_id);
        // Сокет открывается по появлению sessionId вместе со started — до
        // этого момента открывать нечего.
        setStarted(true);
      })
      .catch((cause: Error) => {
        setPlayback('disconnected');
        setError({
          type: 'server',
          message: 'Не удалось начать сессию',
          details: cause.message,
        });
      });
  }, [audio, scenarioId]);

  useEffect(() => {
    if (connection === 'open') setPlayback((current) => (current === 'disconnected' ? 'idle' : current));
    if (connection === 'closed') {
      silenceFollowupRef.current?.pause();
      activeCaptureRef.current = null;
      captureEndingRef.current = false;
      setVoiceActive(false);
      void stopMic();
      setPlayback('disconnected');
    }
  }, [connection, stopMic]);

  // ----------------------------------------------------- отправка = перебивание

  const handleSubmit = useCallback(
    (text: string) => {
      // MessageComposer держит disabled, пока audio === null (аватар ещё
      // грузится) — это защита от невозможного состояния, а не рабочий путь.
      if (!audio) return;
      silenceFollowupRef.current?.beginUserTurn();

      // Текст поверх незаконченной записи: обрываем её, иначе на сервер
      // придут две реплики одного хода — набранная и распознанная.
      const voiceCapture = activeCaptureRef.current;
      if (voiceCapture) {
        activeCaptureRef.current = null;
        captureEndingRef.current = false;
        setVoiceActive(false);
        sendSpeechAbort(voiceCapture);
        void stopMic();
      }

      const interrupted = audio.clock.isPlaying ? genRef.current : null;

      // Шаг 1 (§6): локально и немедленно, без сетевого round-trip.
      cancelPlayback({
        queue: audio.queue,
        freezeSubtitles: () => setSubtitlesFrozen(true),
        resetFace: audio.resetFace,
      });

      // Шаг 2: сообщаем серверу, какое поколение перебиваем.
      sendUserMessage(text, interrupted, avatarModel.id);

      // Новое поколение сервер присвоит сам; локально готовим очередь принять
      // его чанки. Инкремент совпадает с серверным, потому что счётчик растёт
      // ровно на два события: открытие сессии (handleStart выставляет 1) и
      // каждую реплику пользователя. Открытие НОВОГО ЭТАПА поколения не
      // тратит — оно идёт тем же gen_id, что и ход, который его вызвал
      // (gateway/app/orchestrator/pipeline.py::_run_turn).
      genRef.current += 1;
      audio.queue.startGeneration(genRef.current);

      setTranscript((lines) => [...lines, { role: 'user', text }]);
      setCues([]);
      setSubtitlesFrozen(false);
      setPlayback('thinking');
    },
    [audio, avatarModel.id, sendSpeechAbort, sendUserMessage, stopMic],
  );

  // --------------------------------------------------------- голосовой ход

  const handleVoiceStart = useCallback(() => {
    if (!audio || connection !== 'open' || activeCaptureRef.current) return;
    silenceFollowupRef.current?.beginUserTurn();
    const captureId = crypto.randomUUID();
    const captureStartedAt = performance.now();
    const wasPlaying = audio.clock.isPlaying;
    activeCaptureRef.current = captureId;
    captureEndingRef.current = false;
    setVoiceActive(true);
    setVoiceDraft('');
    setVoiceBuffered(false);
    pauseDetectorRef.current.reset();

    // Голос перебивает персонажа ровно тем же протоколом, что и текст (§6):
    // локальная остановка до сети, затем новое поколение.
    const interrupted = wasPlaying ? genRef.current : null;
    cancelPlayback({
      queue: audio.queue,
      freezeSubtitles: () => setSubtitlesFrozen(true),
      resetFace: audio.resetFace,
    });
    genRef.current += 1;
    const stopMs = wasPlaying ? Math.round(performance.now() - captureStartedAt) : undefined;
    voiceTimingRef.current = {
      captureId,
      genId: genRef.current,
      captureStartedAt,
      firstPartialRecorded: false,
      responseAudioRecorded: false,
    };
    setVoiceMetrics({ stopMs });
    audio.queue.startGeneration(genRef.current);
    setCues([]);
    sendSpeechStart(captureId, interrupted, avatarModel.id);
    setPlayback('listening');

    void startMic().catch(() => {
      if (activeCaptureRef.current === captureId) {
        activeCaptureRef.current = null;
        captureEndingRef.current = false;
        setVoiceActive(false);
        sendSpeechAbort(captureId);
        setPlayback('idle');
        silenceFollowupRef.current?.resume();
      }
    });
  }, [audio, avatarModel.id, connection, sendSpeechAbort, sendSpeechStart, startMic]);

  const handleVoiceEnd = useCallback(() => {
    const captureId = activeCaptureRef.current;
    if (!captureId || captureEndingRef.current) return;
    captureEndingRef.current = true;
    if (voiceTimingRef.current?.captureId === captureId) {
      voiceTimingRef.current.speechEndedAt = performance.now();
    }
    setVoiceActive(false);
    setPlayback('recognizing');
    void stopMic().finally(() => {
      // Soniox просит ~200 мс тишины перед ручной финализацией, иначе
      // последняя фонема обрезается.
      sendAudio(new ArrayBuffer(6_400));
      sendSpeechEnd(captureId);
    });
  }, [sendAudio, sendSpeechEnd, stopMic]);
  voiceEndRef.current = handleVoiceEnd;

  useEffect(() => {
    const finalizeWhenHidden = () => {
      if (document.visibilityState === 'hidden' && activeCaptureRef.current) {
        handleVoiceEnd();
      }
    };
    document.addEventListener('visibilitychange', finalizeWhenHidden);
    return () => document.removeEventListener('visibilitychange', finalizeWhenHidden);
  }, [handleVoiceEnd]);

  const switchAvatar = () => {
    if (!audio || playback !== 'idle') return;
    audio.queue.stopAll();
    audio.resetFace();
    setAudio(null);
    setAvatarModel((current) =>
      current.id === AVATAR_MODELS.aith.id ? AVATAR_MODELS.tom : AVATAR_MODELS.aith,
    );
  };

  // ------------------------------------------------------------------ рендер

  const stages = scenario?.stages ?? [];
  const stageIndex = stages.findIndex((s) => s.id === (currentStageId ?? stages[0]?.id));
  const persona = scenario?.persona;

  return (
    <main className="session">
      <header className="session__header card">
        <Link to="/scenarios" className="app__brand session__brand">
          <span className="app__brand-mark">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="m12 3.4 1.9 6 6 1.9-6 1.9-1.9 6-1.9-6-6-1.9 6-1.9Z" />
            </svg>
          </span>
          <span>
            Тренажёр
            <small>{scenario?.title ?? '…'}</small>
          </span>
        </Link>

        {stages.length > 0 && (
          <div className="session__progress">
            <span className="session__progress-label">
              Этап {Math.max(stageIndex, 0) + 1} из {stages.length}
            </span>
            <div className="session__progress-dots">
              {stages.map((stage, i) => (
                <div
                  key={stage.id}
                  className={`session__progress-dot${i <= stageIndex ? ' session__progress-dot--done' : ''}`}
                />
              ))}
            </div>
            {stages[Math.max(stageIndex, 0)] && (
              <StageHint goal={stages[Math.max(stageIndex, 0)].goal} />
            )}
          </div>
        )}

        <PlaybackIndicator state={playback} />
        {/* Push-to-talk переехал в карточку композера (макет «Экран
            сотрудника»), в шапке — только смена модели и завершение. */}
        <div className="session__controls">
          <button
            type="button"
            className="avatar-switch"
            onClick={switchAvatar}
            disabled={!audio || playback !== 'idle'}
          >
            Переключить на {avatarModel.id === AVATAR_MODELS.aith.id ? 'Tom' : 'avatar-aith'}
          </button>
          <button
            type="button"
            className="btn btn-gray session__finish"
            onClick={handleFinish}
            disabled={connection !== 'open' || finished}
          >
            Завершить тренировку
          </button>
        </div>
      </header>

      {error && (
        <p className="session__error" role="alert">
          {error.message}
        </p>
      )}

      <section className="session__main">
        <aside className="card session__history">
          <div className="session__history-head">
            <div>
              <span className="eyebrow">Диалог</span>
              <h2>История</h2>
            </div>
            <span className="session__history-count">{transcript.length} реплик</span>
          </div>
          <ChatPanel
            transcript={transcript}
            cues={cues}
            clock={audio?.clock ?? null}
            isAgentReplying={playback === 'speaking'}
          />
        </aside>

        <div className="session__stage">
          <div className="session__avatar-panel">
            {persona && (
              <div className="session__persona-badge">
                <span className="bento-pill session__badge-dark">{persona.name}</span>
                <span className="bento-pill session__badge-dark">сложность {persona.difficulty} / 5</span>
              </div>
            )}
            <TalkingHeadAvatar
              key={avatarModel.id}
              model={avatarModel}
              isSpeaking={playback === 'speaking'}
              onReady={handleAvatarReady}
              onError={handleAvatarError}
            />
            {audio && <Subtitles clock={audio.clock} cues={cues} frozen={subtitlesFrozen} />}
          </div>

          <section className="card session__composer-card">
            <PushToTalkToggle
              enabled={pushToTalk}
              onChange={setPushToTalk}
              active={voiceActive}
              level={micLevel}
              onStart={handleVoiceStart}
              onEnd={handleVoiceEnd}
              disabled={connection !== 'open' || !audio || finished}
            />
            <MessageComposer
              disabled={connection !== 'open' || !audio || voiceActive || finished}
              isAgentSpeaking={playback === 'speaking'}
              onSubmit={handleSubmit}
              onActivity={() => silenceFollowupRef.current?.postpone()}
            />
            {voiceDraft && <p className="voice-draft">Распознаю: {voiceDraft}</p>}
            {voiceBuffered && (
              <p className="voice-draft voice-draft--buffered">
                {playback === 'recognizing'
                  ? 'Расшифровываю запись — это чуть дольше обычного'
                  : 'Говорите, я записываю — текст появится целиком в конце реплики'}
              </p>
            )}
            {voiceMetrics && (
              <p className="voice-metrics">
                Voice: ACK {formatMetric(voiceMetrics.ackMs)} · partial{' '}
                {formatMetric(voiceMetrics.firstPartialMs)} · final{' '}
                {formatMetric(voiceMetrics.finalizationMs)} · ответ{' '}
                {formatMetric(voiceMetrics.responseTtfaMs)}
                {voiceMetrics.stopMs !== undefined && ` · остановка ${voiceMetrics.stopMs} мс`}
              </p>
            )}
          </section>
        </div>
      </section>

      {/* Аватар грузится (13 МБ GLB) под оверлеем, поэтому он смонтирован
          всегда, а закрывает его этот слой — а не условный рендер сессии. */}
      {!started && <SessionStartOverlay ready={audio !== null} onStart={handleStart} />}
      {finished && <SessionEndOverlay />}
    </main>
  );
}

function formatMetric(value: number | undefined): string {
  return value === undefined ? '—' : `${value} мс`;
}
