/**
 * Экран после окончания тренировки.
 *
 * Показывается по событию `action: finish` от сервера — сразу, не дожидаясь
 * отчёта: оценка идёт сильной моделью и занимает десятки секунд, а сотрудник
 * отчёта всё равно не видит. Баллы и вердикт — экран методиста
 * (`/report/:sessionId`, Claude.md §2), поэтому здесь их нет намеренно.
 */

import { useNavigate } from 'react-router-dom';

export function SessionEndOverlay() {
  const navigate = useNavigate();

  return (
    <div
      className="session-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Тренировка завершена"
    >
      <div className="session-overlay__card">
        <h1 className="session-overlay__title">Тренировка завершена</h1>
        <p className="session-overlay__lead">
          Разговор окончен. Методист получит историю диалога и оценку.
        </p>

        <button
          type="button"
          className="session-overlay__button"
          onClick={() => navigate('/scenarios')}
        >
          На главную
        </button>
      </div>
    </div>
  );
}
