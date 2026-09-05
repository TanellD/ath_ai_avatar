import type { CSSProperties } from 'react';

/**
 * Toggle-to-talk: первый клик начинает явную PTT capture, второй завершает.
 * Такой вариант сохраняет детерминированные границы реплики и нормально
 * работает с тачпадом и клавиатурой, где удержание кнопки неудобно.
 */

interface Props {
  enabled: boolean;
  onChange: (enabled: boolean) => void;
  active: boolean;
  level: number;
  onStart: () => void;
  onEnd: () => void;
  disabled?: boolean;
}

export function PushToTalkToggle({
  enabled,
  onChange,
  active,
  level,
  onStart,
  onEnd,
  disabled = false,
}: Props) {
  return (
    <div className="ptt">
      <label>
        <input
          type="checkbox"
          checked={enabled}
          disabled={disabled || active}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span>Голосовой ввод</span>
      </label>
      {enabled && (
        <button
          type="button"
          className={`ptt__button${active ? ' ptt__button--active' : ''}`}
          disabled={disabled}
          aria-pressed={active}
          onClick={active ? onEnd : onStart}
          style={{ '--mic-level': String(level) } as CSSProperties}
        >
          {active ? 'Закончить запись' : 'Начать говорить'}
        </button>
      )}
    </div>
  );
}
