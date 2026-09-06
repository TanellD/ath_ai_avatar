import type { CSSProperties } from 'react';

/**
 * Toggle-to-talk: первый клик начинает явную PTT capture, второй завершает.
 * Такой вариант сохраняет детерминированные границы реплики и нормально
 * работает с тачпадом, клавиатурой и пальцем, где удержание кнопки неудобно.
 *
 * Кнопка иконочная, а не текстовая. На телефоне главное действие экрана,
 * подписанное словами «Начать говорить», выглядит как обычная ссылка и не
 * читается с одного взгляда; микрофон — узнаваемый значок, и он же даёт
 * круглую цель нажатия в 44px, ниже которой промахиваются пальцем.
 *
 * Иконки две, а не одна: во время записи нужен «стоп», иначе непонятно, что
 * нажатие сейчас остановит, а не начнёт. Подпись остаётся рядом на широком
 * экране и уходит в aria-label на узком, чтобы кнопка не потеряла имя для
 * скринридера.
 */

function MicIcon() {
  return (
    <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 4.5a2.5 2.5 0 0 1 2.5 2.5v5a2.5 2.5 0 0 1-5 0V7A2.5 2.5 0 0 1 12 4.5Z" />
      <path d="M6.5 11.5a5.5 5.5 0 0 0 11 0" />
      <path d="M12 17v2.5" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="7" y="7" width="10" height="10" rx="2.5" />
    </svg>
  );
}

interface Props {
  enabled: boolean;
  onChange: (enabled: boolean) => void;
  active: boolean;
  level: number;
  onStart: () => void;
  onEnd: () => void;
  disabled?: boolean;
  /** Непусто — микрофон недоступен, и это объяснение показывается вместо кнопки. */
  unavailableReason?: string;
}

export function PushToTalkToggle({
  enabled,
  onChange,
  active,
  level,
  onStart,
  onEnd,
  disabled = false,
  unavailableReason = '',
}: Props) {
  const label = active ? 'Закончить запись' : 'Начать говорить';

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

      {/* Причина важнее молчаливо погашенного тумблера: без неё сотрудник не
          поймёт, почему голос не включается, и решит, что сломалось. */}
      {unavailableReason && <p className="ptt__note">{unavailableReason}</p>}

      {enabled && (
        <button
          type="button"
          className={`ptt__button${active ? ' ptt__button--active' : ''}`}
          disabled={disabled}
          aria-pressed={active}
          aria-label={label}
          onClick={active ? onEnd : onStart}
          style={{ '--mic-level': String(level) } as CSSProperties}
        >
          {active ? <StopIcon /> : <MicIcon />}
          <span className="ptt__button-label">{label}</span>
        </button>
      )}
    </div>
  );
}
