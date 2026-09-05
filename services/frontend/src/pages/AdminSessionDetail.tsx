/**
 * Путь одной сессии + Gantt-график операций для выбранного хода (gen_id).
 *
 * «Путь» — все ходы по порядку с этапом и gen_id (§5, конечный автомат);
 * Gantt — из app/tracing.py: чем занят конвейер внутри одного обмена
 * репликами. Оба — для отладки, не для методиста (тот смотрит /report).
 */

import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { adminApi } from '@/api/client';
import { GanttChart } from '@/components/GanttChart';
import type { GenSummary, SessionPath, Span } from '@/contracts/admin';

export function AdminSessionDetail() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [path, setPath] = useState<SessionPath | null>(null);
  const [gens, setGens] = useState<GenSummary[]>([]);
  const [selectedGen, setSelectedGen] = useState<number | null>(null);
  const [spans, setSpans] = useState<Span[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!sessionId) return;
    setLoading(true);
    Promise.all([adminApi.getSessionPath(sessionId), adminApi.listGens(sessionId)])
      .then(([pathData, genData]) => {
        setPath(pathData);
        setGens(genData);
        setSelectedGen((current) => current ?? genData.at(-1)?.gen_id ?? null);
      })
      .catch((cause: Error) => setError(cause.message))
      .finally(() => setLoading(false));
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId || selectedGen === null) {
      setSpans([]);
      return;
    }
    adminApi
      .listSpans(sessionId, selectedGen)
      .then(setSpans)
      .catch((cause: Error) => setError(cause.message));
  }, [sessionId, selectedGen]);

  if (loading) return <p className="page">Загружаем сессию…</p>;
  if (error) return <p className="page page--error">Не удалось загрузить сессию: {error}</p>;
  if (!path) return <p className="page">Сессия не найдена.</p>;

  return (
    <main className="page admin-detail">
      <p>
        <Link to="/admin/sessions">← ко всем сессиям</Link>
        {' · '}
        <Link to={`/report/${path.session.session_id}`}>отчёт методиста</Link>
      </p>
      <h1>Сессия {path.session.session_id}</h1>
      <p className="admin__hint">
        Пользователь: {path.session.user_display_name} · сценарий: {path.session.scenario_id} ·
        статус: {path.session.status} · текущий этап: {path.session.current_stage}
      </p>

      <section className="admin-section">
        <h2>Путь сессии</h2>
        <table className="admin-table">
          <thead>
            <tr>
              <th>#</th>
              <th>gen_id</th>
              <th>Роль</th>
              <th>Этап</th>
              <th>Текст</th>
            </tr>
          </thead>
          <tbody>
            {path.turns.map((turn) => (
              <tr
                key={turn.index}
                className={turn.gen_id === selectedGen ? 'admin-table__row--selected' : ''}
              >
                <td>{turn.index}</td>
                <td>
                  <button
                    type="button"
                    className="admin-genlink"
                    onClick={() => setSelectedGen(turn.gen_id)}
                  >
                    {turn.gen_id}
                  </button>
                </td>
                <td>{turn.role === 'user' ? 'сотрудник' : 'персонаж'}</td>
                <td>{turn.stage_id}</td>
                <td>{turn.text}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="admin-section">
        <h2>Операции хода (Gantt)</h2>

        <label className="admin-gen-select">
          Ход (gen_id):
          <select
            value={selectedGen ?? ''}
            onChange={(event) => setSelectedGen(Number(event.target.value))}
          >
            {gens.map((gen) => (
              <option key={gen.gen_id} value={gen.gen_id}>
                #{gen.gen_id} — {gen.preview || '(пусто)'} ({gen.span_count} операций)
              </option>
            ))}
          </select>
        </label>

        <GanttChart spans={spans} />
      </section>
    </main>
  );
}
