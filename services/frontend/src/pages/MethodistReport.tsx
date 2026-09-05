/**
 * Отчёт методисту — Claude.md §7, §8.
 *
 * Главный экран продукта. Требование к нему одно и жёсткое: каждый балл
 * проверяем за десять секунд. Поэтому цитата стоит непосредственно под баллом,
 * а не в отдельной вкладке «подробности» — лишний клик здесь стоит ровно тех
 * десяти секунд, ради которых всё делалось.
 */

import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';

import { ApiError, gatewayApi, scenarioApi } from '@/api/client';
import { EvidenceQuote } from '@/components/EvidenceQuote';
import type { Report, RubricItem } from '@/contracts/events';

export function MethodistReport() {
  const { sessionId = '' } = useParams();
  const [report, setReport] = useState<Report | null>(null);
  const [rubric, setRubric] = useState<RubricItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  /** 404 — это не поломка, а «сессия ещё не завершена». Ветка отдельная. */
  const [missing, setMissing] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);

  useEffect(() => {
    gatewayApi
      .getReport(sessionId)
      .then(setReport)
      .catch((cause: Error) => {
        if (cause instanceof ApiError && cause.status === 404) setMissing(true);
        else setError(cause.message);
      });
  }, [sessionId]);

  // Названия и шкалы критериев живут в сценарии, а не в отчёте, поэтому
  // рубрику подтягиваем отдельно. У отчётов, сохранённых до появления
  // scenario_id, его нет — тогда просто остаёмся на идентификаторах.
  useEffect(() => {
    if (!report?.scenario_id) return;
    scenarioApi
      .get(report.scenario_id)
      .then((scenario) => setRubric(scenario.rubric))
      .catch(() => setRubric([]));
  }, [report?.scenario_id]);

  const rebuild = useCallback(() => {
    setRebuilding(true);
    setError(null);
    gatewayApi
      .rebuildReport(sessionId)
      .then((fresh) => {
        setReport(fresh);
        setMissing(false);
      })
      .catch((cause: Error) => setError(cause.message))
      .finally(() => setRebuilding(false));
  }, [sessionId]);

  if (missing) {
    return (
      <main className="page">
        <h1>Отчёта нет</h1>
        <p className="admin__hint">
          Сессия ещё не завершена — оценка формируется в конце тренировки. Если
          тренировка закончилась, а отчёта нет, оценка могла не пройти: её можно
          запустить заново.
        </p>
        <button type="button" className="report__rebuild" onClick={rebuild} disabled={rebuilding}>
          {rebuilding ? 'Считаем…' : 'Посчитать оценку'}
        </button>
        {error && <p className="page--error">{error}</p>}
      </main>
    );
  }

  if (error) return <p className="page page--error">Отчёт недоступен: {error}</p>;
  if (!report) return <p className="page">Загружаем отчёт…</p>;

  const byId = new Map(rubric.map((item) => [item.id, item]));
  const isStub = report.model.startsWith('mock');

  return (
    <main className="page report">
      <h1>Итог сессии</h1>

      {isStub && (
        <p className="report__stub" role="alert">
          Оценку посчитала заглушка, а не модель ({report.model}) — содержательных
          выводов в ней нет. Нажмите «Пересчитать», когда настроен реальный
          провайдер LLM.
        </p>
      )}

      <p className="report__verdict">{report.verdict}</p>

      <dl className="report__summary">
        <div>
          <dt>Общий балл</dt>
          <dd>{report.total_score}</dd>
        </div>
        <div>
          <dt>Этапов пройдено</dt>
          <dd>
            {report.stages_completed} из {report.stages_total}
          </dd>
        </div>
        <div>
          <dt>Длительность</dt>
          <dd>{Math.round(report.duration_sec / 60)} мин</dd>
        </div>
        <div>
          {/* §11, пункт 6: счётчик освобождённых часов. */}
          <dt>Освобождено часов методиста</dt>
          <dd>{(report.duration_sec / 3600).toFixed(1)}</dd>
        </div>
      </dl>

      <h2>Оценка по критериям</h2>
      <ul className="report__scores">
        {report.scores.map((score) => {
          // Отчёт несёт только id критерия; название и шкалу берём из рубрики
          // сценария. Её может не быть — у старых отчётов нет scenario_id.
          const item = byId.get(score.criterion_id);
          return (
            <EvidenceQuote
              key={score.criterion_id}
              score={score}
              criterionName={item?.name ?? score.criterion_id}
              scale={item?.scale ?? 5}
            />
          );
        })}
      </ul>

      <p>
        <button type="button" className="report__rebuild" onClick={rebuild} disabled={rebuilding}>
          {rebuilding ? 'Пересчитываем…' : 'Пересчитать оценку'}
        </button>
      </p>

      <h2>История разговора</h2>
      <ol className="report__transcript">
        {report.transcript.map((turn, index) => (
          <li key={index} className={`line line--${turn.role}`}>
            <span className="line__role">
              {turn.role === 'user' ? 'Сотрудник' : 'Персонаж'}:
            </span>{' '}
            {turn.text}
          </li>
        ))}
      </ol>
    </main>
  );
}
