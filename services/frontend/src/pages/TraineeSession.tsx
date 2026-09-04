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
import { TalkingHeadAvatar, type AvatarPlaybackHandle } from '@/avatar/TalkingHeadAvatar';
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

export function TraineeSession() {
  const { scenarioId = '' } = useParams();

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [error, setError] = useState<SessionError | null>(null);
  const [transcript, setTranscript] = useState<ChatTurn[]>([]);
  const [cues, setCues] = useState<SubtitleEvent[]>([]);
  const [subtitlesFrozen, setSubtitlesFrozen] = useState(false);
  const [pushToTalk, setPushToTalk] = useState(false);
  const [playback, setPlayback] = useState<PlaybackState>('disconnected');
  const [audio, setAudio] = useState<AudioRig | null>(null);

  /**
   * Текущее поколение. Именно ref, а не useState: значение читается в
   * обработчике сокета синхронно, и устаревшее замыкание здесь означало бы
   * пропущенный отброс чанка — то есть нарушение метрики 4.
   */
  const genRef = useRef(0);
  const emotionGenerationRef = useRef<number | null>(null);

  const handleAvatarReady = useCallback((handle: AvatarPlaybackHandle) => {
    const clock = new PlaybackClock(handle.audioCtx);
    // Четвёртый параметр — onIdle: единственный правильный источник для
    // индикатора «персонаж говорит». `action` от сервера приходит, когда
    // байты уже ОТПРАВЛЕНЫ, а не когда они доиграли — раньше индикатор либо
    // не гас вовсе (обычный переход stay/next_stage не трогал playback), либо
    // гас слишком рано. Теперь состояние идёт от факта тишины в колонках.
    const queue = new AudioQueue(handle.audioCtx, clock, handle.destination, () =>
      setPlayback('idle'),
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

        case 'report':
          setPlayback('idle');
          // TODO: перевести методиста на экран отчёта / показать ссылку.
          break;

        case 'error':
          setError({ type: 'server', message: event.message, details: event.code });
          break;

        default:
          break;
      }
    },
    [audio],
  );

  const { state: connection, sendUserMessage } = useSessionSocket({
    sessionId,
    onEvent: handleEvent,
    currentGeneration: () => genRef.current,
    onError: setError,
  });

  useEffect(() => {
    if (connection === 'open') setPlayback((current) => (current === 'disconnected' ? 'idle' : current));
    if (connection === 'closed') setPlayback('disconnected');
  }, [connection]);

  // ----------------------------------------------------- отправка = перебивание

  const handleSubmit = useCallback(
    (text: string) => {
      // MessageComposer держит disabled, пока audio === null (аватар ещё
      // грузится) — это защита от невозможного состояния, а не рабочий путь.
      if (!audio) return;

      const interrupted = audio.clock.isPlaying ? genRef.current : null;

      // Шаг 1 (§6): локально и немедленно, без сетевого round-trip.
      cancelPlayback({
        queue: audio.queue,
        freezeSubtitles: () => setSubtitlesFrozen(true),
        resetFace: audio.resetFace,
      });

      // Шаг 2: сообщаем серверу, какое поколение перебиваем.
      sendUserMessage(text, interrupted);

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
    [audio, sendUserMessage],
  );

  // ------------------------------------------------------------------ рендер

  return (
    <main className="session">
      <header className="session__header">
        <PlaybackIndicator state={playback} />
        <PushToTalkToggle enabled={pushToTalk} onChange={setPushToTalk} />
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
            isSpeaking={playback === 'speaking'}
            onReady={handleAvatarReady}
            onError={handleAvatarError}
          />
          {audio && <Subtitles clock={audio.clock} cues={cues} frozen={subtitlesFrozen} />}
        </div>
      </section>

      <MessageComposer
        disabled={connection !== 'open' || !audio}
        isAgentSpeaking={playback === 'speaking'}
        onSubmit={handleSubmit}
      />
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
