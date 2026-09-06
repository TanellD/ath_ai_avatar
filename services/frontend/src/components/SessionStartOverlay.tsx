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
 *
 * И для брифа (§7). Раньше экран не говорил о сценарии НИЧЕГО — сотрудник
 * заходил в разговор, не зная, кто перед ним и чего тот хочет.
 *
 * Отсюда два шага вместо одного. Детали прогона (компания, продукт, цифры)
 * подбираются при СОЗДАНИИ сессии, то есть уже после первого клика: показать
 * их раньше просто нечем, а показать примерами — значит дать сотруднику
 * прочитать одно, а персонажу знать другое. Поэтому первый клик разблокирует
 * звук и заводит сессию, второй входит в разговор, а между ними сотрудник
 * читает обстановку — не под уже говорящего персонажа.
 *
 * Сценарий без брифа проходит этот экран как раньше, одним кликом: второго
 * шага не показывается вовсе.
 */

import { ConsentBanner } from '@/components/ConsentBanner';
import { ScenarioBriefing } from '@/components/ScenarioBriefing';

interface Props {
  /** Аватар загружен и отдал AudioContext — до этого разблокировать нечего. */
  ready: boolean;
  onStart: () => void;
  /** Сессия создаётся: сервер подбирает детали этого прогона. */
  opening?: boolean;
  /** Непусто — значит сессия готова и сотрудник читает обстановку. */
  briefing?: string;
  onEnter?: () => void;
  title?: string;
  /**
   * Доля загрузки модели, 0..1. Основная весит 12.7 МБ: по сотовой сети это
   * десятки секунд, и без доли «Загружаем персонажа…» неотличимо от зависшей
   * страницы.
   */
  progress?: number | null;
}

export function SessionStartOverlay({
  ready,
  onStart,
  opening = false,
  briefing = '',
  onEnter,
  title,
  progress = null,
}: Props) {
  const loading =
    progress === null || progress >= 1
      ? 'Загружаем персонажа…'
      : `Загружаем персонажа… ${Math.round(progress * 100)}%`;
  return (
    <div className="session-overlay" role="dialog" aria-modal="true" aria-label="Начало тренировки">
      <div className="session-overlay__card">
        <h1 className="session-overlay__title">{title || 'Тренировка'}</h1>

        {briefing ? (
          <>
            <p className="session-overlay__lead">Обстановка</p>
            <ScenarioBriefing text={briefing} />
            <button type="button" className="session-overlay__button" onClick={onEnter}>
              Войти в разговор
            </button>
          </>
        ) : (
          <>
            <p className="session-overlay__lead">
              Собеседник начнёт разговор сам — дальше отвечайте ему по ходу диалога.
            </p>

            <ConsentBanner />

            <button
              type="button"
              className="session-overlay__button"
              onClick={onStart}
              disabled={!ready || opening}
            >
              {!ready
                ? loading
                : opening
                  ? 'Готовим ситуацию…'
                  : 'Начать тренировку'}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
