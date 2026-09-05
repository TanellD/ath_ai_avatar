/**
 * WebSocket сессии — Claude.md §6, §7.
 *
 * Хук делает три вещи и больше ничего:
 *   1. держит соединение;
 *   2. **отбрасывает события с чужим gen_id** (§6, шаг 7);
 *   3. отдаёт наверх типизированные события.
 *
 * Логики сценария здесь нет и быть не должно — она вся на сервере.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { gatewayApi } from '@/api/client';
import type {
  AvatarId,
  ClientEvent,
  ServerEvent,
  SilenceTimeout,
  SpeechAbort,
  SpeechEnd,
  SpeechStart,
  UserMessage,
} from '@/contracts/events';
import { sessionError, type SessionError } from '@/types/errors';

export type ConnectionState = 'connecting' | 'open' | 'reconnecting' | 'closed';

/** Задержки переподключения. Растут вдвое, чтобы не долбить упавший сервер. */
/**
 * Инвариант §6, шаг 7: событие чужого поколения не должно дойти до UI.
 *
 * Вынесено отдельно от хука намеренно — это самый жёсткий инвариант клиента,
 * и он обязан проверяться тестом без сокета и без React.
 *
 * `cancel` и `error` — исключения по определению: они говорят о поколении,
 * которое уже не текущее, и отбросить их значит не узнать об отмене.
 */
export function isStaleEvent(event: ServerEvent, currentGeneration: number): boolean {
  if (event.type === 'cancel') return false;
  if (!('gen_id' in event) || event.gen_id === null) return false;
  return event.gen_id !== currentGeneration;
}

const RECONNECT_BASE_MS = 500;
const RECONNECT_MAX_MS = 8_000;
const RECONNECT_ATTEMPTS = 8;

interface Options {
  sessionId: string | null;
  onEvent: (event: ServerEvent) => void;
  /** Текущее поколение. События с другим gen_id отбрасываются. */
  currentGeneration: () => number;
  onError?: (error: SessionError) => void;
  /**
   * Соединение поднялось заново. Поколение сервера могло уйти вперёд, а
   * незавершённая реплика — пропасть вместе со старым сокетом, поэтому
   * вызывающий обязан пересинхронизироваться, а не продолжать с места.
   */
  onReconnect?: () => void;
}

export function useSessionSocket({
  sessionId,
  onEvent,
  currentGeneration,
  onError,
  onReconnect,
}: Options) {
  const socketRef = useRef<WebSocket | null>(null);
  const [state, setState] = useState<ConnectionState>('closed');

  // Держим колбэки в ref, чтобы пересоздание функции у вызывающего не
  // переоткрывало сокет: переподключение посреди реплики — это оборванный звук.
  const handlers = useRef({ onEvent, currentGeneration, onError, onReconnect });
  handlers.current = { onEvent, currentGeneration, onError, onReconnect };

  useEffect(() => {
    if (!sessionId) return;

    // Соединение переоткрывается внутри эффекта, поэтому нужен явный признак
    // ухода: без него закрытие при размонтировании запустило бы переподключение.
    let disposed = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const open = (isRetry: boolean) => {
      const socket = new WebSocket(gatewayApi.sessionSocketUrl(sessionId));
      socketRef.current = socket;
      setState(isRetry ? 'reconnecting' : 'connecting');

      socket.onopen = () => {
        setState('open');
        attempt = 0;
        if (isRetry) handlers.current.onReconnect?.();
      };

      socket.onmessage = (message) => {
        let event: ServerEvent;
        try {
          event = JSON.parse(message.data as string) as ServerEvent;
        } catch (error) {
          handlers.current.onError?.(sessionError('server', String(error)));
          return;
        }

        // Проверка стоит ДО любой обработки — иначе чанк отменённого
        // поколения успевает попасть в очередь воспроизведения.
        if (isStaleEvent(event, handlers.current.currentGeneration())) return;

        handlers.current.onEvent(event);
      };

      // onerror всегда сопровождается onclose, и переподключение живёт только
      // там: иначе одна неудачная попытка планировала бы две новых.
      socket.onerror = () => {
        handlers.current.onError?.(sessionError('websocket'));
      };

      socket.onclose = (event) => {
        if (disposed) return;
        // Коды 4xxx сервер шлёт осознанно (сессия или сценарий не найдены).
        // Повтор даст тот же отказ восемь раз подряд и только спрячет причину.
        if (event.code >= 4000 && event.code < 5000) {
          setState('closed');
          handlers.current.onError?.(
            sessionError('websocket', event.reason || `соединение закрыто (${event.code})`),
          );
          return;
        }
        if (attempt >= RECONNECT_ATTEMPTS) {
          setState('closed');
          handlers.current.onError?.(
            sessionError('websocket', 'соединение потеряно, обновите страницу'),
          );
          return;
        }
        const delay = Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS);
        attempt += 1;
        setState('reconnecting');
        timer = setTimeout(() => open(true), delay);
      };
    };

    open(false);

    return () => {
      disposed = true;
      if (timer !== undefined) clearTimeout(timer);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [sessionId]);

  const send = useCallback((event: ClientEvent) => {
    const socket = socketRef.current;
    if (socket?.readyState !== WebSocket.OPEN) {
      handlers.current.onError?.(sessionError('websocket', 'socket is not open'));
      return;
    }
    socket.send(JSON.stringify(event));
  }, []);

  const sendUserMessage = useCallback(
    (text: string, interrupts: number | null, avatarId: AvatarId) => {
      const event: UserMessage = { type: 'user_message', text, interrupts, avatar_id: avatarId };
      send(event);
    },
    [send],
  );

  const sendSpeechStart = useCallback(
    (captureId: string, interrupts: number | null, avatarId: AvatarId) => {
      const event: SpeechStart = {
        type: 'speech_start',
        capture_id: captureId,
        interrupts,
        avatar_id: avatarId,
        mode: 'ptt',
        audio_format: 'pcm_s16le',
        sample_rate: 16000,
        num_channels: 1,
      };
      send(event);
    },
    [send],
  );

  const sendSpeechEnd = useCallback(
    (captureId: string) => {
      const event: SpeechEnd = { type: 'speech_end', capture_id: captureId };
      send(event);
    },
    [send],
  );

  const sendSpeechAbort = useCallback(
    (captureId: string) => {
      const event: SpeechAbort = { type: 'speech_abort', capture_id: captureId };
      send(event);
    },
    [send],
  );

  const sendSilenceTimeout = useCallback(
    (phase: SilenceTimeout['phase'], avatarId: AvatarId) => {
      send({ type: 'silence_timeout', phase, avatar_id: avatarId });
    },
    [send],
  );

  const sendAudio = useCallback((frame: ArrayBuffer) => {
    const socket = socketRef.current;
    if (socket?.readyState !== WebSocket.OPEN) return false;
    socket.send(frame);
    return true;
  }, []);

  return {
    state,
    send,
    sendUserMessage,
    sendSpeechStart,
    sendSpeechEnd,
    sendSpeechAbort,
    sendSilenceTimeout,
    sendAudio,
  };
}
