/**
 * Список проведённых тренировок — Claude.md §2: «после сессии методист
 * получает историю разговора и итоговую оценку».
 *
 * До этой страницы отчёт существовал, но попасть в него можно было только
 * зная UUID сессии: ссылок на `/report/:sessionId` не было нигде.
 *
 * Не путать с админ-панелью (`/admin/sessions`): та показывает внутренности
 * конвейера (поколения, спаны, Gantt) и является инструментом отладки. Здесь —
 * продуктовый экран: что за сценарий, когда, готов ли отчёт.
 */

import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';

import { gatewayApi, scenarioApi } from '@/api/client';
import type { ScenarioSummary, SessionSummaryItem } from '@/contracts/events';

const STATUS_LABEL: Record<string, string> = {
  active: 'не завершена',
  finished: 'завершена',
  abandoned: 'брошена',
};

/**
 * Оценку считает сильная модель уже после конца тренировки — на живой
 * сессии это заняло 39 секунд. Всё это время отчёта в базе ещё нет, и
 * страница обязана показывать «считается», а не «нет»: иначе методист
 * решает, что оценка не сформировалась, и жмёт пересчёт вручную.
 */
const POLL_INTERVAL_MS = 4000;
/** Потолок ожидания. Дальше молчать нельзя — оценка, видимо, упала. */
const POLL_LIMIT_MS = 3 * 60 * 1000;

function isPending(session: SessionSummaryItem): boolean {
  return session.status === 'finished' && !session.has_report;
}

export function MethodistSessions() {
  const [sessions, setSessions] = useState<SessionSummaryItem[]>([]);
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  /** Ждать перестали — оценка не пришла за POLL_LIMIT_MS. */
  const [gaveUp, setGaveUp] = useState(false);
  const startedAt = useRef(Date.now());

  useEffect(() => {
    // Сценарии — одной выборкой на страницу, чтобы показать название вместо
    // id; запрос на строку тут был бы N+1 на ровном месте.
    Promise.all([gatewayApi.listSessions(), scenarioApi.list()])
      .then(([sessionList, scenarioList]) => {
        setSessions(sessionList);
        setScenarios(scenarioList);
      })
      .catch((cause: Error) => setError(cause.message))
      .finally(() => setLoading(false));
  }, []);

  // Опрос только пока есть чего ждать: список перезапрашивается, пока хоть
  // одна завершённая сессия сидит без отчёта.
  const waiting = !gaveUp && sessions.some(isPending);
  useEffect(() => {
    if (!waiting) return;

    const timer = setInterval(() => {
      if (Date.now() - startedAt.current > POLL_LIMIT_MS) {
        setGaveUp(true);
        return;
      }
      gatewayApi.listSessions().then(setSessions).catch(() => {
        // Молча: список уже показан, а мигать ошибкой на фоновом опросе —
        // худшее, что можно сделать с открытой страницей.
      });
    }, POLL_INTERVAL_MS);

    return () => clearInterval(timer);
  }, [waiting]);

  if (loading) return <p className="page">Загружаем сессии…</p>;
  if (error) return <p className="page page--error">Не удалось загрузить сессии: {error}</p>;

  const titleById = new Map(scenarios.map((s) => [s.id, s.title]));

  return (
    <main className="page">
      <h1>Тренировки</h1>

      {sessions.length === 0 && (
        <p className="admin__hint">
          Проведённых тренировок пока нет. Запустите сценарий на странице «Сценарии».
        </p>
      )}

      {sessions.length > 0 && (
        <div className="table-scroll">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Сценарий</th>
                <th>Дата</th>
                <th>Статус</th>
                <th>Реплик</th>
                <th>Отчёт</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((session) => (
                <tr key={session.session_id}>
                  <td>{titleById.get(session.scenario_id) ?? session.scenario_id}</td>
                  <td>{new Date(session.created_at).toLocaleString('ru-RU')}</td>
                  <td>
                    <span className={`admin-status admin-status--${session.status}`}>
                      {STATUS_LABEL[session.status] ?? session.status}
                    </span>
                  </td>
                  <td>{session.turn_count}</td>
                  <td>
                    {session.has_report ? (
                      <Link
                        className="report-chip report-chip--ready"
                        to={`/report/${session.session_id}`}
                      >
                        Отчёт
                      </Link>
                    ) : isPending(session) && !gaveUp ? (
                      <span className="report-chip report-chip--pending skeleton-shimmer">
                        Считается…
                      </span>
                    ) : isPending(session) ? (
                      // Ждали дольше разумного: оценка, скорее всего, упала —
                      // на странице отчёта есть кнопка пересчёта.
                      <Link className="report-chip report-chip--none" to={`/report/${session.session_id}`}>
                        не сформирован
                      </Link>
                    ) : (
                      <span className="report-chip report-chip--none">нет</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
