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
  onActivity?: () => void;
}

export function MessageComposer({ disabled, isAgentSpeaking, onSubmit, onActivity }: Props) {
  const [text, setText] = useState('');

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || disabled) return;

    onSubmit(trimmed);
    setText('');
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
          setText(event.target.value);
          onActivity?.();
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
