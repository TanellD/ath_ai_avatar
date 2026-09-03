/**
 * Gantt-график операций одного хода (character_reply / tts_synthesize /
 * classify) — чисто для отладки конвейера, не продуктовый UI (Claude.md §7
 * не описывает эту страницу).
 *
 * Каждая полоса — один span из app/tracing.py: start_ms/end_ms относительно
 * начала ЭТОГО хода. Цвет — по типу операции, рамка — по статусу
 * (error/cancelled), подпись — операция + текст (label), обрезанный.
 */

const OPERATION_COLOR: Record<string, string> = {
  character_reply: '#4f7cff',
  tts_synthesize: '#31b58c',
  classify: '#c98a2c',
};

const FALLBACK_COLOR = '#8b8fa3';

const ROW_HEIGHT = 32;
const ROW_GAP = 6;
const LABEL_WIDTH = 160;
const AXIS_HEIGHT = 24;
const CHART_WIDTH = 760;

function operationColor(operation: string): string {
  return OPERATION_COLOR[operation] ?? FALLBACK_COLOR;
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

interface SpanLike {
  seq: number;
  operation: string;
  label: string;
  start_ms: number;
  end_ms: number;
  status: string;
  error: string | null;
}

export function GanttChart({ spans }: { spans: SpanLike[] }) {
  if (spans.length === 0) {
    return <p className="gantt__empty">Нет данных по операциям для этого хода.</p>;
  }

  const maxEnd = Math.max(...spans.map((s) => s.end_ms), 1);
  const plotWidth = CHART_WIDTH - LABEL_WIDTH;
  const height = AXIS_HEIGHT + spans.length * (ROW_HEIGHT + ROW_GAP);
  const msToX = (ms: number) => LABEL_WIDTH + (ms / maxEnd) * plotWidth;

  const tickCount = 5;
  const ticks = Array.from({ length: tickCount + 1 }, (_, i) => Math.round((maxEnd / tickCount) * i));

  return (
    <svg
      className="gantt"
      viewBox={`0 0 ${CHART_WIDTH} ${height}`}
      width="100%"
      role="img"
      aria-label="Gantt-график операций хода"
    >
      {ticks.map((tick) => (
        <g key={tick}>
          <line
            x1={msToX(tick)}
            x2={msToX(tick)}
            y1={AXIS_HEIGHT}
            y2={height}
            className="gantt__gridline"
          />
          <text x={msToX(tick)} y={AXIS_HEIGHT - 8} className="gantt__tick">
            {tick} мс
          </text>
        </g>
      ))}

      {spans.map((span, i) => {
        const y = AXIS_HEIGHT + i * (ROW_HEIGHT + ROW_GAP);
        const x = msToX(span.start_ms);
        const width = Math.max(msToX(span.end_ms) - x, 2);
        const title = `${span.operation} · ${span.label} · ${span.end_ms - span.start_ms} мс${
          span.error ? ` · ошибка: ${span.error}` : ''
        }`;

        return (
          <g key={span.seq}>
            <text x={0} y={y + ROW_HEIGHT / 2 + 4} className="gantt__row-label">
              {truncate(`#${span.seq} ${span.operation}`, 22)}
            </text>
            <rect
              x={x}
              y={y}
              width={width}
              height={ROW_HEIGHT}
              rx={4}
              fill={operationColor(span.operation)}
              className={`gantt__bar gantt__bar--${span.status}`}
            >
              <title>{title}</title>
            </rect>
            <text x={x + 6} y={y + ROW_HEIGHT / 2 + 4} className="gantt__bar-label">
              {truncate(span.label, Math.max(Math.floor(width / 7), 0))}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
