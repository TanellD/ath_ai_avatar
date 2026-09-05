/**
 * Список сценариев — Claude.md §2, §11.
 *
 * Первый шаг демо: «методист выбирает шаблон, меняет два поля, запускает — за
 * минуту». Отсюда одно проектное решение: шаблон не редактируется на месте, а
 * копируется. Иначе первый же прогон испортит эталон для всей команды.
 *
 * Вёрстка карточек — по макету front/Дашборд методиста.dc.html (вкладка
 * «Сценарии», класс .product из clarity-ui.css). Персонажей на выбор макет
 * рисует несколько на карточку — здесь их ровно один (`persona_name`,
 * реальное поле контракта): смена персонажа сценарием пока не поддержана
 * backend'ом, дорисовывать несуществующий переключатель не стал.
 */

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { scenarioApi } from '@/api/client';
import type { ScenarioSummary } from '@/contracts/events';

export function MethodistScenarios() {
  const [items, setItems] = useState<ScenarioSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    scenarioApi
      .list()
      .then(setItems)
      .catch((cause: Error) => setError(cause.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="page">Загружаем сценарии…</p>;
  if (error) return <p className="page page--error">Не удалось загрузить сценарии: {error}</p>;

  return (
    <main className="page page--wide">
      <section className="card hero-card">
        <span className="eyebrow">Библиотека</span>
        <h1>Сценарии</h1>
        <p className="lead">
          Персонаж, этапы и рубрика хранятся вместе. Выберите сценарий, чтобы пройти его
          самостоятельно, или посмотрите готовые отчёты в админ-панели.
        </p>
      </section>

      {items.length === 0 && <p>Сценариев пока нет.</p>}

      <section className="scenario-grid">
        {items.map((item) => (
          <article key={item.id} className="product">
            <div className="product-ic">
              <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="m12 3.6 8.4 4.4-8.4 4.4-8.4-4.4Z" />
                <path d="m3.6 12.4 8.4 4.4 8.4-4.4" />
              </svg>
            </div>
            <h3>{item.title}</h3>
            <p>
              Персонаж: {item.persona_name} · этапов: {item.stages_count} · критериев в
              рубрике: {item.rubric_count}
            </p>
            <div className="product-foot">
              <span>{item.stages_count} этапа(ов)</span>
              <Link className="arrow-btn" to={`/session/${item.id}`} aria-label={`Пройти «${item.title}»`}>
                <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4.5 12h14" />
                  <path d="m12.5 6 6 6-6 6" />
                </svg>
              </Link>
            </div>
          </article>
        ))}
      </section>

      {/* TODO: редактор сценария (§7) — правка полей персонажа, этапов и рубрики,
          плюс копирование шаблона перед правкой. */}
    </main>
  );
}
