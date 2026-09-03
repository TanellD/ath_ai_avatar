/**
 * Контракты админ-панели — зеркало services/gateway/app/api/admin.py.
 *
 * Намеренно отдельно от events.ts: это внутренний инструмент отладки
 * конвейера (сессии/ходы/спаны с gen_id), а не продукт по Claude.md §7 —
 * смешивать с продуктовыми контрактами не нужно.
 */

export interface SessionSummary {
  session_id: string;
  scenario_id: string;
  user_id: string;
  user_display_name: string;
  status: string;
  current_stage: string;
  turn_count: number;
  created_at: string;
}

export interface AdminTurn {
  index: number;
  gen_id: number;
  role: string;
  text: string;
  stage_id: string;
  ts: number;
}

export interface SessionPath {
  session: SessionSummary;
  turns: AdminTurn[];
}

export interface GenSummary {
  gen_id: number;
  preview: string;
  span_count: number;
}

export type SpanStatus = 'ok' | 'error' | 'cancelled';

export interface Span {
  gen_id: number;
  seq: number;
  operation: string;
  label: string;
  start_ms: number;
  end_ms: number;
  status: SpanStatus;
  error: string | null;
}

/** Одна строка нагрузки по типу операции — /admin/load. */
export interface OperationLoad {
  operation: string;
  service: string;
  call_count: number;
  avg_duration_ms: number;
  p95_duration_ms: number;
  error_count: number;
  cancelled_count: number;
}

/** Один столбик графика активности — подпись HH:MM:SS, не дата. */
export interface TimeBucket {
  label: string;
  count: number;
}

export interface LoadStats {
  operations: OperationLoad[];
  sessions_total: number;
  sessions_by_status: Record<string, number>;
  sessions_timeline: TimeBucket[];
  activity_timeline: TimeBucket[];
}
