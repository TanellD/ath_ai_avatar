/**
 * Ошибки по сервисам во времени — docs/bugs_front.md №6.
 *
 * Один график, несколько сервисов, общая шкала бакетов (все таймлайны в
 * `error_timeline` посчитаны с одним и тем же `since`/`until`/`bucket_seconds`
 * в get_load_stats — сравнивать их по индексу бакета корректно).
 */

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { AXIS_TICK, CHART_COLORS } from '@/components/chartTheme';
import type { TimeBucket } from '@/contracts/admin';

const SERVICE_COLOR: Record<string, string> = {
  'ai-service': CHART_COLORS.danger,
  'speech-service': CHART_COLORS.blue,
};

export function ErrorTimelineChart({ timeline }: { timeline: Record<string, TimeBucket[]> }) {
  const services = Object.keys(timeline).sort();

  if (services.length === 0) {
    return (
      <div className="load-timeline load-timeline--errors">
        <h3 className="load-timeline__title">Ошибки по сервисам</h3>
        <p className="admin__hint">Ошибок за окно наблюдения нет.</p>
      </div>
    );
  }

  // Одна точка на бакет, по колонке на сервис — recharts хочет плоские
  // строки, а не серию на сервис.
  const buckets = timeline[services[0]];
  const data = buckets.map((bucket, i) => {
    const row: Record<string, string | number> = { label: bucket.label.slice(3) };
    for (const service of services) {
      row[service] = timeline[service][i]?.count ?? 0;
    }
    return row;
  });

  return (
    <div className="load-timeline load-timeline--errors">
      <h3 className="load-timeline__title">Ошибки по сервисам</h3>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={data} margin={{ top: 6, right: 12, bottom: 0, left: -24 }}>
          <CartesianGrid stroke={CHART_COLORS.line} vertical={false} />
          <XAxis dataKey="label" tick={AXIS_TICK} stroke={CHART_COLORS.line} minTickGap={24} />
          <YAxis tick={AXIS_TICK} stroke={CHART_COLORS.line} allowDecimals={false} width={44} />
          <Tooltip labelFormatter={(label) => `Время ${String(label)}`} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {services.map((service) => (
            <Line
              key={service}
              type="monotone"
              dataKey={service}
              name={service}
              stroke={SERVICE_COLOR[service] ?? CHART_COLORS.ink3}
              strokeWidth={2}
              dot={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
