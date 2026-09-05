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
  SpeechAbort,
  SpeechEnd,
  SpeechStart,
  UserMessage,
} from '@/contracts/events';
import { sessionError, type SessionError } from '@/types/errors';

export type ConnectionState = 'connecting' | 'open' | 'closed';

interface Options {
  sessionId: string | null;
  onEvent: (event: ServerEvent) => void;
  /** Текущее поколение. События с другим gen_id отбрасываются. */
  currentGeneration: () => number;
  onError?: (error: SessionError) => void;
}

export function useSessionSocket({
  sessionId,
  onEvent,
  currentGeneration,
  onError,
}: Options) {
  const socketRef = useRef<WebSocket | null>(null);
  const [state, setState] = useState<ConnectionState>('closed');

  // Держим колбэки в ref, чтобы пересоздание функции у вызывающего не
  // переоткрывало сокет: переподключение посреди реплики — это оборванный звук.
  const handlers = useRef({ onEvent, currentGeneration, onError });
  handlers.current = { onEvent, currentGeneration, onError };

  useEffect(() => {
    if (!sessionId) return;

    const socket = new WebSocket(gatewayApi.sessionSocketUrl(sessionId));
    socketRef.current = socket;
    setState('connecting');

    socket.onopen = () => setState('open');

    socket.onmessage = (message) => {
      let event: ServerEvent;
      try {
        event = JSON.parse(message.data as string) as ServerEvent;
      } catch (error) {
        handlers.current.onError?.(sessionError('server', String(error)));
        return;
      }

      // Инвариант §6, шаг 7. Проверка стоит ДО любой обработки — иначе чанк
      // отменённого поколения успевает попасть в очередь воспроизведения.
      //
      // cancel и error — исключения: они по определению говорят о поколении,
      // которое уже не текущее, и отбросить их значит не узнать об отмене.
      if ('gen_id' in event && event.gen_id !== null && event.type !== 'cancel') {
        if (event.gen_id !== handlers.current.currentGeneration()) return;
      }

      handlers.current.onEvent(event);
    };

    socket.onerror = () => {
      handlers.current.onError?.(sessionError('websocket'));
    };

    socket.onclose = () => {
      setState('closed');
      // TODO: переподключение с экспоненциальной задержкой. Референсный проект
      // его тоже не имеет, и на защите обрыв сети означает конец демо.
    };

    return () => {
      socket.close();
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
    sendAudio,
  };
}
