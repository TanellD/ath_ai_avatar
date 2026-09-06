/**
 * Ввод реплики — триггер протокола отмены (Claude.md §6).
 *
 * **Отправка сообщения и есть перебивание.** Последовательность на клиенте:
 *
 *   1. cancelPlayback() — локально, синхронно, без сети (шаг 1);
 *   2. отправка user_message { interrupts: gen_id } (шаг 2).
 *
 * Именно в этом порядке. Сначала тишина, потом сеть — иначе бюджет в 300 мс
 * начинает зависеть от RTT.
 *
 * [STT] В голосовой фазе те же два шага делает VAD onset, вызывая ту же самую
 * cancelPlayback(). Компонент к тому моменту станет вторым способом ввода, а не
 * будет заменён.
 */

import { useState, type FormEvent, type KeyboardEvent } from 'react';

interface Props {
  disabled: boolean;
  /** Персонаж сейчас говорит — значит отправка его перебьёт. */
  isAgentSpeaking: boolean;
  onSubmit: (text: string) => void;
  /**
   * Есть ли прямо сейчас непустой черновик в поле. Таймер молчания (§1)
   * ориентируется на это, а не на факт недавнего нажатия клавиши: человек,
   * формулирующий длинный ответ, может надолго замереть между нажатиями, не
   * переставая при этом отвечать — раньше персонаж в такой паузе перебивал
   * его собственной репликой.
   */
  onDraftChange?: (hasText: boolean) => void;
}

export function MessageComposer({ disabled, isAgentSpeaking, onSubmit, onDraftChange }: Props) {
  const [text, setText] = useState('');

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || disabled) return;

    onSubmit(trimmed);
    setText('');
    onDraftChange?.(false);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter отправляет, Shift+Enter переносит строку: реплика в устном
    // разговоре — одна-две фразы, многострочный ввод здесь исключение.
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit(event as unknown as FormEvent);
    }
  };

  return (
    <form className="composer" onSubmit={submit}>
      <textarea
        className="composer__input"
        value={text}
        onChange={(event) => {
          const value = event.target.value;
          setText(value);
          onDraftChange?.(value.trim().length > 0);
        }}
        onKeyDown={handleKeyDown}
        placeholder="Ваша реплика. Enter — отправить."
        rows={2}
        disabled={disabled}
        autoFocus
      />
      <button className="composer__submit" type="submit" disabled={disabled || !text.trim()}>
        {isAgentSpeaking ? 'Перебить' : 'Ответить'}
      </button>
    </form>
  );
}
