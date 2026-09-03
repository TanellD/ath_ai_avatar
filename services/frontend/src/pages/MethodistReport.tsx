/**
 * Отчёт методисту — Claude.md §7, §8.
 *
 * Главный экран продукта. Требование к нему одно и жёсткое: каждый балл
 * проверяем за десять секунд. Поэтому цитата стоит непосредственно под баллом,
 * а не в отдельной вкладке «подробности» — лишний клик здесь стоит ровно тех
 * десяти секунд, ради которых всё делалось.
 */

import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';

import { gatewayApi } from '@/api/client';
import { EvidenceQuote } from '@/components/EvidenceQuote';
import type { Report } from '@/contracts/events';

export function MethodistReport() {
  const { sessionId = '' } = useParams();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    gatewayApi
      .getReport(sessionId)
      .then(setReport)
      .catch((cause: Error) => setError(cause.message));
  }, [sessionId]);

  if (error) return <p className="page page--error">Отчёт недоступен: {error}</p>;
  if (!report) return <p className="page">Загружаем отчёт…</p>;

  return (
    <main className="page report">
      <h1>Итог сессии</h1>

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
        {report.scores.map((score) => (
          <EvidenceQuote
            key={score.criterion_id}
            score={score}
            // TODO: подтянуть название и шкалу критерия из сценария —
            // сейчас показываем идентификатор.
            criterionName={score.criterion_id}
            scale={5}
          />
        ))}
      </ul>

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
