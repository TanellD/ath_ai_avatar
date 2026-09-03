/**
 * Индикатор состояния — Claude.md §8.
 *
 * В голосовой фазе требование звучит как «слушаю / говорит персонаж /
 * распознаю: пользователь должен понимать, слышат ли его». В текстовой фазе
 * половина состояний ещё не применима, но само требование — да: человек должен
 * видеть, ждёт ли система его ответа или ещё думает.
 *
 * [STT] Состояния 'listening' и 'recognizing' объявлены заранее и появятся
 * вместе с микрофоном. См. docs/stt-phase.md.
 */

export type PlaybackState =
  | 'disconnected'
  | 'idle'
  | 'thinking'
  | 'speaking'
  // [STT] пока не используются
  | 'listening'
  | 'recognizing';

const LABELS: Record<PlaybackState, string> = {
  disconnected: 'Нет связи',
  idle: 'Ваш ход',
  thinking: 'Персонаж думает',
  speaking: 'Персонаж говорит',
  listening: 'Слушаю',
  recognizing: 'Распознаю',
};

interface Props {
  state: PlaybackState;
}

export function PlaybackIndicator({ state }: Props) {
  return (
    <div className={`indicator indicator--${state}`} role="status" aria-live="polite">
      <span className="indicator__dot" aria-hidden="true" />
      <span className="indicator__label">{LABELS[state]}</span>
    </div>
  );
}
