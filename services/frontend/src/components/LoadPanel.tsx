/**
 * Нагрузка на дашборде: сколько вызовов ушло в какой downstream-сервис, с
 * какой латентностью, и сессии/активность во времени. Источник — /admin/load
 * (агрегат по app/db/models.py::SpanRow, см. docs/data.md).
 *
 * Таймлайны — бакеты по секундам (подпись MM:SS), не по дням: тестовые
 * сессии этого проекта идут пачками за минуты, дневной график почти всегда
 * состоял бы из одной точки «сегодня» и ничего бы не показывал.
 *
 * Рисует recharts. Время — линиями: шестьдесят тонких столбиков читались
 * как шум. Латентность операций осталась столбиками, но горизонтальными:
 * это три несвязанные категории, линия между ними означала бы динамику,
 * которой там нет.
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { AXIS_TICK, CHART_COLORS } from '@/components/chartTheme';
import { ErrorTimelineChart } from '@/components/ErrorTimelineChart';
import type { LoadStats, TimeBucket } from '@/contracts/admin';

const SERVICE_LABEL: Record<string, string> = {
  'ai-service': 'ai-service',
  'speech-service': 'speech-service',
};

/** HH:MM:SS -> MM:SS: часы не нужны в 30-минутном окне. */
function shortLabel(label: string): string {
  return label.slice(3);
}

function Timeline({ title, buckets }: { title: string; buckets: TimeBucket[] }) {
  if (buckets.length === 0) {
    return (
      <div className="load-timeline">
        <h3 className="load-timeline__title">{title}</h3>
        <p className="admin__hint">Нет данных за окно наблюдения.</p>
      </div>
    );
  }

  const data = buckets.map((bucket) => ({ label: shortLabel(bucket.label), count: bucket.count }));

  return (
    <div className="load-timeline">
      <h3 className="load-timeline__title">{title}</h3>
      <ResponsiveContainer width="100%" height={160}>
        <LineChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: -24 }}>
          <CartesianGrid stroke={CHART_COLORS.line} vertical={false} />
          <XAxis dataKey="label" tick={AXIS_TICK} stroke={CHART_COLORS.line} minTickGap={24} />
          <YAxis tick={AXIS_TICK} stroke={CHART_COLORS.line} allowDecimals={false} width={44} />
          <Tooltip
            labelFormatter={(label) => `Время ${String(label)}`}
            formatter={(value) => [String(value), 'событий']}
          />
          <Line
            type="monotone"
            dataKey="count"
            stroke={CHART_COLORS.blue}
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

const LATENCY_OPERATIONS: Array<{ operation: string; label: string }> = [
  { operation: 'character_reply', label: 'Генерация текста' },
  { operation: 'tts_synthesize', label: 'Озвучка' },
  { operation: 'evaluate', label: 'Оценка' },
];

function LatencyChart({ stats }: { stats: LoadStats }) {
  const byOperation = new Map(stats.operations.map((op) => [op.operation, op]));
  const data = LATENCY_OPERATIONS.flatMap(({ operation, label }) => {
    const op = byOperation.get(operation);
    return op ? [{ label, avg: op.avg_duration_ms, p95: op.p95_duration_ms }] : [];
  });

  if (data.length === 0) {
    return (
      <div className="load-timeline">
        <h3 className="load-timeline__title">Латентность операций</h3>
        <p className="admin__hint">Данных по операциям пока нет.</p>
      </div>
    );
  }

  return (
    <div className="load-timeline">
      <h3 className="load-timeline__title">Латентность операций, мс</h3>
      <ResponsiveContainer width="100%" height={160}>
        <BarChart data={data} layout="vertical" margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={CHART_COLORS.line} horizontal={false} />
          <XAxis type="number" tick={AXIS_TICK} stroke={CHART_COLORS.line} />
          <YAxis
            type="category"
            dataKey="label"
            tick={AXIS_TICK}
            stroke={CHART_COLORS.line}
            width={110}
          />
          <Tooltip formatter={(value, name) => [`${String(value)} мс`, String(name)]} />
          <Bar dataKey="avg" name="среднее" fill={CHART_COLORS.blue} radius={[0, 4, 4, 0]} />
          <Bar dataKey="p95" name="p95" fill={CHART_COLORS.ink3} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
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
        <div className="load-summary__item">
          {/* Claude.md §11, п.6: агрегат по всем сессиям. Цифра по одной
              сессии живёт в её отчёте, это разные вопросы. */}
          <span className="load-summary__value">{stats.freed_hours} ч</span>
          <span className="load-summary__label">освобождено методисту</span>
        </div>
        {Object.entries(stats.sessions_by_status).map(([status, count]) => (
          <div className="load-summary__item" key={status}>
            <span className="load-summary__value">{count}</span>
            <span className="load-summary__label">{status}</span>
          </div>
        ))}
      </div>

      <div className="table-scroll">
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
      </div>

      <div className="load-timelines">
        <Timeline title="Сессии, создано" buckets={stats.sessions_timeline} />
        <Timeline title="Активность (спаны)" buckets={stats.activity_timeline} />
        <LatencyChart stats={stats} />
      </div>

      <ErrorTimelineChart timeline={stats.error_timeline} />
    </section>
  );
}
