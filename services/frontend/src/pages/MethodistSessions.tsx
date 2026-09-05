/**
 * Журнал сессий методиста — вкладка «Сессии» из front/Дашборд методиста.dc.html.
 *
 * Данные — тот же `/admin/sessions`, что и у отладочной админ-панели
 * (см. contracts/admin.ts): заводить второй, продуктовый эндпоинт с теми же
 * полями ради разделения смыслов не стал — это было бы дублированием ради
 * дублирования. Отличие только в том, ЧТО показываем: без Gantt и span'ов,
 * только то, что реально имеет смысл методисту — кто, какой сценарий, какой
 * статус, сколько ходов.
 *
 * Из макета сознательно не воспроизведено: колонки «оценка»/«длительность»
 * (нужен отдельный запрос отчёта на сессию — у нас нет списочного эндпоинта
 * с готовыми баллами, N+1 запросов ради красивой колонки — плохая цена) и
 * фильтры по сценарию/периоду (чисто декоративные в макете, без реальной
 * логики фильтрации на бэкенде). «Открыть отчёт» ведёт на `/report/:id`
 * только если сессия завершена — отчёт формируется один раз, в конце (§7).
 */

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { adminApi } from '@/api/client';
import type { SessionSummary } from '@/contracts/admin';

export function MethodistSessions() {
  const [items, setItems] = useState<SessionSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // /admin/sessions уже отдаёт по убыванию created_at (см. admin_repository.py) —
    // сортировать на клиенте не нужно.
    adminApi
      .listSessions()
      .then(setItems)
      .catch((cause: Error) => setError(cause.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="page">Загружаем сессии…</p>;
  if (error) return <p className="page page--error">Не удалось загрузить сессии: {error}</p>;

  return (
    <main className="page page--wide">
      <section className="card hero-card">
        <span className="eyebrow">Журнал</span>
        <h1>Сессии</h1>
        <p className="lead">
          {items.length} прохождений. Отчёт с баллами и цитатами доступен сразу после завершения
          разговора.
        </p>
      </section>

      <section className="card sessions-table">
        {items.length === 0 && <p>Сессий пока нет.</p>}
        {items.length > 0 && (
          <div className="sessions-table__body">
            {items.map((item) => {
              const finished = item.status === 'finished';
              return (
                <div key={item.session_id} className="sessions-row row-hover">
                  <div className="sessions-row__person">{item.user_display_name}</div>
                  <div className="sessions-row__scenario">{item.scenario_id}</div>
                  <div className="sessions-row__date">
                    {new Date(item.created_at).toLocaleString('ru-RU')}
                  </div>
                  <div className="sessions-row__stage">{item.current_stage}</div>
                  <div className="sessions-row__turns">{item.turn_count} ход(ов)</div>
                  <div>
                    <span className={`bento-pill sessions-status sessions-status--${item.status}`}>
                      {STATUS_LABEL[item.status] ?? item.status}
                    </span>
                  </div>
                  {finished ? (
                    <Link className="arrow-btn" to={`/report/${item.session_id}`} aria-label="Открыть отчёт">
                      <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M7 17 17 7" />
                        <path d="M8.5 7H17v8.5" />
                      </svg>
                    </Link>
                  ) : (
                    <span className="arrow-btn arrow-btn--disabled" aria-hidden="true">
                      <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M7 17 17 7" />
                        <path d="M8.5 7H17v8.5" />
                      </svg>
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </main>
  );
}

const STATUS_LABEL: Record<string, string> = {
  active: 'идёт',
  finished: 'завершена',
  abandoned: 'прервана',
};
