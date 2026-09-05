/**
 * Дашборд админ-панели: список сессий. Внутренний инструмент отладки
 * конвейера, не роль по Claude.md §2 — см. app/api/admin.py.
 */

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { adminApi } from '@/api/client';
import { LoadPanel } from '@/components/LoadPanel';
import type { LoadStats, SessionSummary } from '@/contracts/admin';

export function AdminSessions() {
  const [items, setItems] = useState<SessionSummary[]>([]);
  const [load, setLoad] = useState<LoadStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([adminApi.listSessions(), adminApi.getLoad()])
      .then(([sessions, loadStats]) => {
        setItems(sessions);
        setLoad(loadStats);
      })
      .catch((cause: Error) => setError(cause.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="page">Загружаем сессии…</p>;
  if (error) return <p className="page page--error">Не удалось загрузить сессии: {error}</p>;

  return (
    <main className="page">
      <h1>Админ-панель · сессии</h1>
      <p className="admin__hint">
        Отладочный просмотр внутреннего состояния конвейера: путь сессии и Gantt-график
        операций по каждому ходу. Для Gantt по конкретной сессии со всеми сообщениями
        сразу и с учётом параллелизма есть отдельный скрипт: scripts/session_gantt.py.
      </p>

      {load && <LoadPanel stats={load} />}

      <section className="admin-section">
        <h2>Сессии</h2>

        {items.length === 0 && <p>Сессий пока нет.</p>}

        <table className="admin-table">
          <thead>
            <tr>
              <th>Сессия</th>
              <th>Сценарий</th>
              <th>Пользователь</th>
              <th>Статус</th>
              <th>Этап</th>
              <th>Ходов</th>
              <th>Создана</th>
              <th>Отчёт</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.session_id}>
                <td>
                  <Link to={`/admin/sessions/${item.session_id}`}>
                    {item.session_id.slice(0, 8)}…
                  </Link>
                </td>
                <td>{item.scenario_id}</td>
                <td>{item.user_display_name}</td>
                <td>
                  <span className={`admin-status admin-status--${item.status}`}>
                    {item.status}
                  </span>
                </td>
                <td>{item.current_stage}</td>
                <td>{item.turn_count}</td>
                <td>{new Date(item.created_at).toLocaleString('ru-RU')}</td>
                <td>
                  {/* Ссылка безусловная: админка — отладочный инструмент, а
                      страница отчёта сама скажет «сессия не завершена». */}
                  <Link to={`/report/${item.session_id}`}>Отчёт</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  );
}
