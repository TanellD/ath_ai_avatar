/**
 * Экран перед началом тренировки — docs/agent-initiative.md.
 *
 * Не оформительский приём: инициативу держит агент (Claude.md §1), персонаж
 * заговаривает первым — а значит к моменту первого звука пользователь ещё
 * ничего не нажал. Политика автоплея в браузерах требует жеста пользователя,
 * иначе `AudioContext` останется suspended и реплика уйдёт в тишину. Клик по
 * этой кнопке и есть тот жест.
 *
 * Заодно это естественное место для уведомления о записи (§3, §10): его и так
 * положено показать до начала разговора.
 */

import { ConsentBanner } from '@/components/ConsentBanner';

interface Props {
  /** Аватар загружен и отдал AudioContext — до этого разблокировать нечего. */
  ready: boolean;
  onStart: () => void;
}

export function SessionStartOverlay({ ready, onStart }: Props) {
  return (
    <div className="session-overlay" role="dialog" aria-modal="true" aria-label="Начало тренировки">
      <div className="session-overlay__card">
        <h1 className="session-overlay__title">Тренировка</h1>
        <p className="session-overlay__lead">
          Собеседник начнёт разговор сам — дальше отвечайте ему по ходу диалога.
        </p>

        <ConsentBanner />

        <button
          type="button"
          className="session-overlay__button"
          onClick={onStart}
          disabled={!ready}
        >
          {ready ? 'Начать тренировку' : 'Загружаем персонажа…'}
        </button>
      </div>
    </div>
  );
}
