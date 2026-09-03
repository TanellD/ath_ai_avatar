/**
 * Push-to-talk — консервативный запасной режим из Claude.md §6.
 *
 *   «Если AEC/эхо капризничают перед защитой: сотрудник удерживает клавишу,
 *    пока говорит. Это возвращает детерминизм текстового ввода (явный сигнал
 *    начала и конца, нет ложных срабатываний) ценой естественности.»
 *
 * Компонент существует с самого начала намеренно. Запасной режим, который надо
 * писать в последний вечер перед защитой, — это не запасной режим.
 *
 * [STT] Сейчас переключатель ни на что не влияет: голосового ввода нет.
 * Заготовка удерживает место в интерфейсе и в состоянии сессии.
 */

interface Props {
  enabled: boolean;
  onChange: (enabled: boolean) => void;
  /** В текстовой фазе — true: переключать нечего. */
  disabled?: boolean;
}

export function PushToTalkToggle({ enabled, onChange, disabled = true }: Props) {
  return (
    <label className="ptt">
      <input
        type="checkbox"
        checked={enabled}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>Push-to-talk {disabled && '(доступно при голосовом вводе)'}</span>
    </label>
  );
}
