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

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { gatewayApi, scenarioApi } from '@/api/client';
import type { ScenarioSummary, SessionSummaryItem } from '@/contracts/events';

const STATUS_LABEL: Record<string, string> = {
  active: 'не завершена',
  finished: 'завершена',
  abandoned: 'брошена',
};

export function MethodistSessions() {
  const [sessions, setSessions] = useState<SessionSummaryItem[]>([]);
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

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
                    <Link to={`/report/${session.session_id}`}>Открыть</Link>
                  ) : (
                    <span className="admin__hint">нет</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
