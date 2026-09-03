/**
 * Нагрузка на дашборде: сколько вызовов ушло в какой downstream-сервис, с
 * какой латентностью, и сессии/активность во времени. Источник — /admin/load
 * (агрегат по app/db/models.py::SpanRow, см. docs/data.md).
 *
 * Таймлайны — бакеты по секундам (подпись MM:SS), не по дням: тестовые
 * сессии этого проекта идут пачками за минуты, дневной график почти всегда
 * состоял бы из одного столбика «сегодня» и ничего бы не показывал.
 */

import type { LoadStats, TimeBucket } from '@/contracts/admin';

const SERVICE_LABEL: Record<string, string> = {
  'ai-service': 'ai-service',
  'speech-service': 'speech-service',
};

function Timeline({ title, buckets }: { title: string; buckets: TimeBucket[] }) {
  const max = Math.max(...buckets.map((b) => b.count), 1);
  const labelEvery = Math.max(Math.ceil(buckets.length / 10), 1);

  return (
    <div className="load-timeline">
      <h3 className="load-timeline__title">{title}</h3>
      {buckets.length === 0 ? (
        <p className="admin__hint">Нет данных за окно наблюдения.</p>
      ) : (
        <div className="load-timeline__bars">
          {buckets.map((b, i) => (
            <div className="load-timeline__col" key={`${b.label}-${i}`} title={`${b.label}: ${b.count}`}>
              <div
                className="load-timeline__bar"
                style={{ height: `${(b.count / max) * 100}%` }}
              />
              {/* HH:MM:SS -> MM:SS: часы не нужны в 30-минутном окне */}
              {i % labelEvery === 0 && (
                <span className="load-timeline__label">{b.label.slice(3)}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function LoadPanel({ stats }: { stats: LoadStats }) {
  return (
    <section className="admin-section">
      <h2>Нагрузка</h2>

      <div className="load-summary">
        <div className="load-summary__item">
          <span className="load-summary__value">{stats.sessions_total}</span>
          <span className="load-summary__label">сессий всего</span>
        </div>
        {Object.entries(stats.sessions_by_status).map(([status, count]) => (
          <div className="load-summary__item" key={status}>
            <span className="load-summary__value">{count}</span>
            <span className="load-summary__label">{status}</span>
          </div>
        ))}
      </div>

      <table className="admin-table">
        <thead>
          <tr>
            <th>Операция</th>
            <th>Сервис</th>
            <th>Вызовов</th>
            <th>Средняя, мс</th>
            <th>p95, мс</th>
            <th>Ошибок</th>
            <th>Отменено</th>
          </tr>
        </thead>
        <tbody>
          {stats.operations.map((op) => (
            <tr key={op.operation}>
              <td>{op.operation}</td>
              <td>{SERVICE_LABEL[op.service] ?? op.service}</td>
              <td>{op.call_count}</td>
              <td>{op.avg_duration_ms}</td>
              <td>{op.p95_duration_ms}</td>
              <td className={op.error_count > 0 ? 'load-cell--warn' : ''}>{op.error_count}</td>
              <td>{op.cancelled_count}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="load-timelines">
        <Timeline title="Сессии, создано" buckets={stats.sessions_timeline} />
        <Timeline title="Активность (спаны)" buckets={stats.activity_timeline} />
      </div>
    </section>
  );
}
