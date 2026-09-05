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
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';

import { gatewayApi } from '@/api/client';
import { AudioQueue } from '@/audio/AudioQueue';
import { PlaybackClock } from '@/audio/PlaybackClock';
import { cancelPlayback } from '@/audio/cancelPlayback';
import { useMicCapture } from '@/audio/mic/useMicCapture';
import {
  AVATAR_MODELS,
  TalkingHeadAvatar,
  type AvatarModelConfig,
  type AvatarPlaybackHandle,
} from '@/avatar/TalkingHeadAvatar';
import { ChatPanel, type ChatTurn } from '@/components/ChatPanel';
import { ConsentBanner } from '@/components/ConsentBanner';
import { MessageComposer } from '@/components/MessageComposer';
import { PlaybackIndicator, type PlaybackState } from '@/components/PlaybackIndicator';
import { PushToTalkToggle } from '@/components/PushToTalkToggle';
import type { ServerEvent, SubtitleEvent } from '@/contracts/events';
import { Subtitles } from '@/subtitles/Subtitles';
import type { SessionError } from '@/types/errors';
import { useSessionSocket } from '@/ws/useSessionSocket';

interface AudioRig {
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
  const [avatarModel, setAvatarModel] = useState<AvatarModelConfig>(AVATAR_MODELS.aith);

  /**
   * Текущее поколение. Именно ref, а не useState: значение читается в
   * обработчике сокета синхронно, и устаревшее замыкание здесь означало бы
   * пропущенный отброс чанка — то есть нарушение метрики 4.
   */
  const genRef = useRef(0);
  const emotionGenerationRef = useRef<number | null>(null);
  const activeCaptureRef = useRef<string | null>(null);
  const captureEndingRef = useRef(false);
  const voiceTimingRef = useRef<VoiceTimingMarks | null>(null);

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
      () => setPlayback('idle'),
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
        console.info('[voice-metric]', { capture_id: timing.captureId, response_ttfa_ms: responseTtfaMs });
      },
    );
    setAudio({ clock, queue, resetFace: handle.resetFace, setEmotion: handle.setEmotion });
  }, []);

  const handleAvatarError = useCallback((message: string) => {
    setError({ type: 'audio', message: 'Не удалось загрузить аватара', details: message });
  }, []);

  // ------------------------------------------------------------ создание сессии

  useEffect(() => {
    let cancelled = false;

    gatewayApi
      .createSession(scenarioId)
      .then((response) => {
        if (!cancelled) setSessionId(response.session_id);
      })
      .catch((cause: Error) => {
        if (!cancelled) setError({ type: 'server', message: 'Не удалось начать сессию', details: cause.message });
      });

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
        case 'token':
          setPlayback('speaking');
          setTranscript((lines) => appendAgentToken(lines, event.text));
          break;

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
          // Обычный переход (stay/next_stage) не обязан гасить индикатор —
          // это делает AudioQueue.onIdle, когда реплика реально доиграет.
          // Исключение — предохранитель: если очередь и так уже пуста
          // (ответ пришёл вовсе без звука, например при ошибке TTS),
          // action — единственный сигнал, что ход завершён.
          if (audio?.queue.isIdle) setPlayback('idle');
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
              setError({ type: 'audio', message: 'Речь не распознана, попробуйте ещё раз' });
            }
          }
          break;

        case 'report':
          setPlayback('idle');
          // TODO: перевести методиста на экран отчёта / показать ссылку.
          break;

        case 'error':
          if (event.code.startsWith('stt_') || event.code.includes('voice_capture')) {
            activeCaptureRef.current = null;
            captureEndingRef.current = false;
            setVoiceActive(false);
            setVoiceBuffered(false);
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
   * после обновления страницы он начинается с нуля, а сервер продолжает с
   * сохранённого значения — и тогда фильтр по gen_id отбросил бы вообще всё.
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

  const {
    state: connection,
    sendUserMessage,
    sendSpeechStart,
    sendSpeechEnd,
    sendSpeechAbort,
    sendAudio,
  } = useSessionSocket({
    sessionId,
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
      if (sessionId) void syncGeneration(sessionId);
    },
  });

  const { start: startMic, stop: stopMic, level: micLevel } = useMicCapture({
    onFrame: (frame) => {
      if (activeCaptureRef.current && !captureEndingRef.current) sendAudio(frame);
    },
    onError: (message) => {
      setError({ type: 'audio', message });
    },
  });

  useEffect(() => {
    if (connection === 'open') setPlayback((current) => (current === 'disconnected' ? 'idle' : current));
    if (connection === 'closed') {
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
      // его чанки. Инкремент здесь совпадает с серверным, потому что счётчик
      // растёт ровно на одно сообщение пользователя.
      genRef.current += 1;
      audio.queue.startGeneration(genRef.current);

      setTranscript((lines) => [...lines, { role: 'user', text }]);
      setCues([]);
      setSubtitlesFrozen(false);
      setPlayback('thinking');
    },
    [audio, avatarModel.id, sendSpeechAbort, sendUserMessage, stopMic],
  );

  const handleVoiceStart = useCallback(() => {
    if (!audio || connection !== 'open' || activeCaptureRef.current) return;
    const captureId = crypto.randomUUID();
    const captureStartedAt = performance.now();
    const wasPlaying = audio.clock.isPlaying;
    activeCaptureRef.current = captureId;
    captureEndingRef.current = false;
    setVoiceActive(true);
    setVoiceDraft('');
    setVoiceBuffered(false);

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
      // Soniox recommends about 200 ms of trailing silence before manual
      // finalize so that the last phoneme isn't clipped.
      sendAudio(new ArrayBuffer(6_400));
      sendSpeechEnd(captureId);
    });
  }, [sendAudio, sendSpeechEnd, stopMic]);

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

  return (
    <main className="session">
      <header className="session__header">
        <PlaybackIndicator state={playback} />
        <div className="session__header-actions">
          <button
            type="button"
            className="avatar-switch"
            onClick={switchAvatar}
            disabled={!audio || playback !== 'idle'}
          >
            Переключить на {avatarModel.id === AVATAR_MODELS.aith.id ? 'Tom' : 'avatar-aith'}
          </button>
          <PushToTalkToggle
            enabled={pushToTalk}
            onChange={setPushToTalk}
            active={voiceActive}
            level={micLevel}
            onStart={handleVoiceStart}
            onEnd={handleVoiceEnd}
            disabled={connection !== 'open' || !audio}
          />
        </div>
      </header>

      <ConsentBanner />

      {error && (
        <p className="session__error" role="alert">
          {error.message}
        </p>
      )}

      <section className="session__main">
        <ChatPanel
          transcript={transcript}
          cues={cues}
          clock={audio?.clock ?? null}
          isAgentReplying={playback === 'speaking'}
        />

        <div className="session__stage">
          <TalkingHeadAvatar
            key={avatarModel.id}
            model={avatarModel}
            isSpeaking={playback === 'speaking'}
            onReady={handleAvatarReady}
            onError={handleAvatarError}
          />
          {audio && <Subtitles clock={audio.clock} cues={cues} frozen={subtitlesFrozen} />}
        </div>
      </section>

      <MessageComposer
        disabled={connection !== 'open' || !audio || voiceActive}
        isAgentSpeaking={playback === 'speaking'}
        onSubmit={handleSubmit}
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
    </main>
  );
}

/** Токены персонажа дописываются в последнюю его реплику, а не создают новую. */
function appendAgentToken(lines: ChatTurn[], token: string): ChatTurn[] {
  const last = lines[lines.length - 1];
  if (last?.role === 'agent') {
    return [...lines.slice(0, -1), { ...last, text: last.text + token }];
  }
  return [...lines, { role: 'agent', text: token }];
}

function formatMetric(value: number | undefined): string {
  return value === undefined ? '—' : `${value} мс`;
}
