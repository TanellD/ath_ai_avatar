import type { CSSProperties } from 'react';

/**
 * Кнопка голосового ввода — заменяет прежний PushToTalkToggle (чекбокс
 * «Голосовой ввод» + отдельная текстовая кнопка, появлявшаяся только после
 * него). Один значок, всегда на месте рядом с полем ввода: клик начинает
 * запись, повторный клик её заканчивает («один раз нажал — один раз
 * отжал»), без промежуточного шага явного включения режима.
 *
 * Toggle-to-talk, не push (удержание): границы реплики детерминированы, и
 * это нормально работает с тачпадом/тачскрином, где удержание неудобно.
 */

interface Props {
  active: boolean;
  level: number;
  onStart: () => void;
  onEnd: () => void;
  disabled?: boolean;
}

export function MicButton({ active, level, onStart, onEnd, disabled = false }: Props) {
  const label = active ? 'Закончить голосовую реплику' : 'Начать голосовую реплику';

  return (
    <button
      type="button"
      className={`mic-btn${active ? ' mic-btn--active' : ''}`}
      disabled={disabled}
      aria-pressed={active}
      aria-label={label}
      title={label}
      onClick={active ? onEnd : onStart}
      style={{ '--mic-level': String(level) } as CSSProperties}
    >
      {/* Заливка внутри — уровень микрофона (Claude.md §8: сотрудник должен
          видеть, что его слышат, до первого транскрипта). */}
      <span className="mic-btn__level" aria-hidden="true" />
      <svg
        className="mic-btn__icon"
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <rect x="9" y="2.5" width="6" height="11" rx="3" />
        <path d="M5 11a7 7 0 0 0 14 0" />
        <path d="M12 18v3.5" />
        <path d="M8.4 21.5h7.2" />
      </svg>
    </button>
  );
}
