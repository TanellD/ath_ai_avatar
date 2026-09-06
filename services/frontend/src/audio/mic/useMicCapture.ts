import { useCallback, useEffect, useRef, useState } from 'react';

export type MicState = 'idle' | 'listening' | 'recognizing' | 'denied' | 'unavailable';

export interface MicCapture {
  state: MicState;
  level: number;
  start: () => Promise<void>;
  stop: () => Promise<void>;
}

interface Options {
  onFrame: (frame: ArrayBuffer) => void;
  onError: (message: string) => void;
}

export const MIC_CONSTRAINTS: MediaTrackConstraints = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
  channelCount: 1,
};

export function useMicCapture({ onFrame, onError }: Options): MicCapture {
  const callbacks = useRef({ onFrame, onError });
  callbacks.current = { onFrame, onError };
  const resources = useRef<{
    stream: MediaStream;
    context: AudioContext;
    worklet: AudioWorkletNode;
  } | null>(null);
  const startEpoch = useRef(0);
  const [state, setState] = useState<MicState>('idle');
  const [level, setLevel] = useState(0);

  const cleanup = useCallback(async () => {
    const current = resources.current;
    resources.current = null;
    if (!current) return;
    current.stream.getTracks().forEach((track) => track.stop());
    current.worklet.disconnect();
    await current.context.close();
  }, []);

  const start = useCallback(async () => {
    if (resources.current) return;
    const epoch = ++startEpoch.current;
    if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
      setState('unavailable');
      callbacks.current.onError('Браузер не поддерживает захват речи');
      throw new Error('microphone capture is unavailable');
    }
    let stream: MediaStream | null = null;
    let context: AudioContext | null = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: MIC_CONSTRAINTS });
      if (epoch !== startEpoch.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      context = new AudioContext();
      await context.audioWorklet.addModule('/pcm-capture.worklet.js');
      if (epoch !== startEpoch.current) {
        stream.getTracks().forEach((track) => track.stop());
        await context.close();
        return;
      }
      const source = context.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(context, 'pcm-capture-processor');
      const silent = context.createGain();
      silent.gain.value = 0;
      worklet.port.onmessage = (event: MessageEvent) => {
        if (event.data?.type !== 'pcm') return;
        const frame = event.data.buffer as ArrayBuffer;
        const samples = new Int16Array(frame);
        let peak = 0;
        for (const sample of samples) peak = Math.max(peak, Math.abs(sample) / 32768);
        setLevel(peak);
        callbacks.current.onFrame(frame);
      };
      source.connect(worklet).connect(silent).connect(context.destination);
      resources.current = { stream, context, worklet };
      stream = null;
      context = null;
      setState('listening');
    } catch (cause) {
      stream?.getTracks().forEach((track) => track.stop());
      if (context && context.state !== 'closed') await context.close();
      await cleanup();
      const denied = cause instanceof DOMException && cause.name === 'NotAllowedError';
      setState(denied ? 'denied' : 'unavailable');
      callbacks.current.onError(
        denied ? 'Разрешите доступ к микрофону' : 'Не удалось включить микрофон',
      );
      throw cause;
    }
  }, [cleanup]);

  const stop = useCallback(async () => {
    startEpoch.current += 1;
    const current = resources.current;
    if (!current) return;
    setState('recognizing');
    // `flushed` приходит из process() воркета, а он не тикает, если
    // AudioContext успел уйти в suspended (например, вкладку свернули —
    // именно тогда TraineeSession и дёргает stop() по visibilitychange).
    // Без таймаута promise висел бы вечно, а с ним — speech_end никогда бы
    // не ушёл, и UI застревал бы в 'recognizing' до серверного watchdog.
    await new Promise<void>((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve();
      };
      const previous = current.worklet.port.onmessage;
      current.worklet.port.onmessage = (event: MessageEvent) => {
        previous?.call(current.worklet.port, event);
        if (event.data?.type === 'flushed') finish();
      };
      // Не тайминг мимики/субтитров (Claude.md §3 запрещает именно это) — это
      // предохранитель на случай зависшего postMessage-хендшейка с воркетом,
      // от аудио-часов никак не зависящий.
      // eslint-disable-next-line no-restricted-globals
      const timer = setTimeout(finish, 300);
      current.worklet.port.postMessage({ type: 'flush' });
    });
    await cleanup();
    setLevel(0);
  }, [cleanup]);

  useEffect(() => () => void cleanup(), [cleanup]);

  return { state, level, start, stop };
}
