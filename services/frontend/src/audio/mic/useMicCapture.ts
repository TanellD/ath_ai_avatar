/**
 * Захват микрофона — фаза [STT]. Определение без реализации.
 *
 * См. README.md в этом каталоге и docs/stt-phase.md.
 * Ничто в проекте отсюда не импортирует.
 */

export type MicState = 'idle' | 'listening' | 'recognizing' | 'denied' | 'unavailable';

export interface MicCapture {
  state: MicState;
  /** Уровень сигнала 0..1 — для индикатора «вас слышно». */
  level: number;
  start: () => Promise<void>;
  stop: () => void;
}

/**
 * Ограничения потока фиксируем здесь заранее — это не «настройки по вкусу»,
 * а требование Claude.md §3 и §8.
 *
 * `echoCancellation` обязателен: без него микрофон слышит персонажа из
 * колонок, VAD принимает это за речь пользователя, и персонаж перебивает сам
 * себя. На демо страхуемся наушниками (§10), но полагаться только на них
 * нельзя — «прогнать на чужом вайфае через проектор» (§11) означает, что
 * условия будут не те, в которых отлаживались.
 */
export const MIC_CONSTRAINTS: MediaTrackConstraints = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
  channelCount: 1,
  sampleRate: 16000,
};

// export function useMicCapture(): MicCapture {
//   // 1. navigator.mediaDevices.getUserMedia({ audio: MIC_CONSTRAINTS })
//   //    Ошибку NotAllowedError мапить в VoiceError { type: 'permission' } —
//   //    пользователь должен видеть, что дело в разрешении, а не в сети.
//   //
//   // 2. AudioWorklet (не ScriptProcessor — он deprecated и работает в
//   //    основном потоке, то есть отдаёт фреймы с джиттером).
//   //
//   // 3. Фреймы уходят в useVad() локально И в сокет на gateway. Локальный
//   //    путь не ждёт сетевого: на нём держится метрика 3.
//   //
//   // 4. Микрофон захвачен ВСЁ время, включая речь персонажа (§8) — иначе
//   //    перебить голосом нельзя.
//   throw new Error('[STT] not implemented — см. README.md');
// }
