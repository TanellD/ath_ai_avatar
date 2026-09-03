/**
 * Экран сотрудника — Claude.md §8.
 *
 * Здесь сходятся все инварианты клиента, поэтому читать этот файл стоит вместе
 * с §6:
 *
 *   - поколение (`genRef`) — источник истины для фильтрации событий;
 *   - отправка реплики вызывает cancelPlayback() ДО отправки в сокет;
 *   - аудио-чанки идут только через AudioQueue, который сам отбрасывает чужие;
 *   - субтитры и мимика читают время у PlaybackClock и больше нигде.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';

import { gatewayApi } from '@/api/client';
import { AudioQueue } from '@/audio/AudioQueue';
import { PlaybackClock } from '@/audio/PlaybackClock';
import { cancelPlayback } from '@/audio/cancelPlayback';
import { SimliAvatar } from '@/avatar/SimliAvatar';
import { ConsentBanner } from '@/components/ConsentBanner';
import { MessageComposer } from '@/components/MessageComposer';
import { PlaybackIndicator, type PlaybackState } from '@/components/PlaybackIndicator';
import { PushToTalkToggle } from '@/components/PushToTalkToggle';
import type { ServerEvent, SubtitleEvent } from '@/contracts/events';
import { Subtitles } from '@/subtitles/Subtitles';
import type { SessionError } from '@/types/errors';
import { useSessionSocket } from '@/ws/useSessionSocket';

interface TranscriptLine {
  role: 'user' | 'agent';
  text: string;
}

export function TraineeSession() {
  const { scenarioId = '' } = useParams();

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [error, setError] = useState<SessionError | null>(null);
  const [transcript, setTranscript] = useState<TranscriptLine[]>([]);
  const [cues, setCues] = useState<SubtitleEvent[]>([]);
  const [subtitlesFrozen, setSubtitlesFrozen] = useState(false);
  const [pushToTalk, setPushToTalk] = useState(false);
  const [playback, setPlayback] = useState<PlaybackState>('disconnected');

  /**
   * Текущее поколение. Именно ref, а не useState: значение читается в
   * обработчике сокета синхронно, и устаревшее замыкание здесь означало бы
   * пропущенный отброс чанка — то есть нарушение метрики 4.
   */
  const genRef = useRef(0);

  const audio = useMemo(() => {
    const context = new AudioContext();
    const clock = new PlaybackClock(context);
    return { context, clock, queue: new AudioQueue(context, clock) };
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

  useEffect(() => () => void audio.context.close(), [audio]);

  // -------------------------------------------------------------- события WS

  const handleEvent = useCallback(
    (event: ServerEvent) => {
      switch (event.type) {
        case 'token':
          setPlayback('speaking');
          setTranscript((lines) => appendAgentToken(lines, event.text));
          break;

        case 'audio_chunk':
          // Очередь сама сверит gen_id ещё раз — намеренное дублирование
          // проверки: чанк мог быть декодирован уже после перебивания.
          void audio.queue.enqueue({ genId: event.gen_id, seq: event.seq, data: event.data });
          break;

        case 'subtitle':
          setCues((current) => [...current, event]);
          break;

        case 'action':
          if (event.action === 'evaluate' || event.action === 'finish') setPlayback('idle');
          break;

        case 'cancel':
          // Сервер подтвердил отмену. Локально мы её уже выполнили — это
          // подстраховка для случая, когда отмену инициировал не клиент.
          if (event.gen_id !== genRef.current) audio.queue.stopAll();
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
      const interrupted = audio.clock.isPlaying ? genRef.current : null;

      // Шаг 1 (§6): локально и немедленно, без сетевого round-trip.
      cancelPlayback({
        queue: audio.queue,
        freezeSubtitles: () => setSubtitlesFrozen(true),
        resetFace: () => undefined, // LipSync сам вернёт рот в 0 по часам.
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

      <section className="session__stage">
        <SimliAvatar clock={audio.clock} />
        <Subtitles clock={audio.clock} cues={cues} frozen={subtitlesFrozen} />
      </section>

      <section className="session__transcript">
        {transcript.map((line, index) => (
          <p key={index} className={`line line--${line.role}`}>
            <span className="line__role">{line.role === 'user' ? 'Вы' : 'Персонаж'}:</span>{' '}
            {line.text}
          </p>
        ))}
      </section>

      <MessageComposer
        disabled={connection !== 'open'}
        isAgentSpeaking={playback === 'speaking'}
        onSubmit={handleSubmit}
      />
    </main>
  );
}

/** Токены персонажа дописываются в последнюю его реплику, а не создают новую. */
function appendAgentToken(lines: TranscriptLine[], token: string): TranscriptLine[] {
  const last = lines[lines.length - 1];
  if (last?.role === 'agent') {
    return [...lines.slice(0, -1), { ...last, text: last.text + token }];
  }
  return [...lines, { role: 'agent', text: token }];
}
