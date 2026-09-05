/**
 * Отчёт методисту — Claude.md §7, §8.
 *
 * Главный экран продукта. Требование к нему одно и жёсткое: каждый балл
 * проверяем за десять секунд. Поэтому цитата стоит непосредственно под баллом,
 * а не в отдельной вкладке «подробности» — лишний клик здесь стоит ровно тех
 * десяти секунд, ради которых всё делалось.
 *
 * Вёрстка — по вкладке «Разбор сессии» из front/Дашборд методиста.dc.html:
 * вердикт на тёмной плашке, статистика сессии рядом, баллы с цитатами ниже.
 * Раздел «Прохождение этапов» из макета не воспроизведён — контракт Report
 * не отдаёт постадийный статус (только stages_completed/stages_total), а
 * рисовать его по выдуманным данным значило бы врать методисту в его же
 * инструменте проверки.
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
    <main className="page page--wide report">
      <section className="card hero-card">
        <span className="eyebrow">Разбор сессии {report.session_id.slice(0, 8)}…</span>
        <h1>Итог сессии</h1>
      </section>

      {isStub && (
        <p className="report__stub" role="alert">
          Оценку посчитала заглушка, а не модель ({report.model}) — содержательных
          выводов в ней нет. Нажмите «Пересчитать», когда настроен реальный
          провайдер LLM.
        </p>
      )}

      <section className="report__top">
        <article className="report__verdict-card">
          <span className="eyebrow report__verdict-eyebrow">Вердикт</span>
          <p className="report__verdict-text">{report.verdict}</p>
        </article>

        <article className="card report__stats">
          <div className="stats-grid">
            <div className="stat">
              <b>{report.total_score}</b>
              <span>общий балл</span>
            </div>
            <div className="stat">
              <b>
                {report.stages_completed} / {report.stages_total}
              </b>
              <span>этапов пройдено</span>
            </div>
            <div className="stat">
              <b>{Math.round(report.duration_sec / 60)} мин</b>
              <span>длительность</span>
            </div>
            <div className="stat">
              {/* §11, пункт 6: счётчик освобождённых часов. */}
              <b>{(report.duration_sec / 3600).toFixed(1)} ч</b>
              <span>освобождено методисту</span>
            </div>
          </div>
        </article>
      </section>

      <section className="card">
        <div className="report__scores-head">
          <div>
            <span className="eyebrow">Оценка</span>
            <h2>Баллы по критериям</h2>
          </div>
          <button type="button" className="report__rebuild" onClick={rebuild} disabled={rebuilding}>
            {rebuilding ? 'Пересчитываем…' : 'Пересчитать оценку'}
          </button>
        </div>
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
      </section>

      <section className="card">
        <div className="report__transcript-head">
          <div>
            <span className="eyebrow">Транскрипт</span>
            <h2>История разговора</h2>
          </div>
          <span className="report__transcript-count">{report.transcript.length} реплик</span>
        </div>
        <ol className="report__transcript">
          {report.transcript.map((turn, index) => (
            <li key={index} className={`transcript-line transcript-line--${turn.role}`}>
              <span className="transcript-line__who">
                {turn.role === 'user' ? 'Сотрудник' : 'Персонаж'}
              </span>
              <span className="transcript-line__text">{turn.text}</span>
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}
