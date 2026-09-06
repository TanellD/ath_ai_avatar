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
 *
 * Карточка целиком ведёт на /scenarios/:id (ScenarioPreview) — что вообще
 * проверяется в сценарии, — а не сразу в сессию: раньше единственным
 * действием была стрелка «Пройти», и узнать заранее, что за тренировка,
 * было нельзя (docs/bugs_front.md №8). Поиск и теги (№10) — клиентские:
 * сценариев в проекте единицы, серверная фильтрация не нужна.
 */

import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { scenarioApi } from '@/api/client';
import type { ScenarioSummary } from '@/contracts/events';

export function MethodistScenarios() {
  const [items, setItems] = useState<ScenarioSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [activeTags, setActiveTags] = useState<string[]>([]);

  useEffect(() => {
    scenarioApi
      .list()
      .then(setItems)
      .catch((cause: Error) => setError(cause.message))
      .finally(() => setLoading(false));
  }, []);

  const allTags = useMemo(
    () => [...new Set(items.flatMap((item) => item.tags))].sort(),
    [items],
  );

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return items.filter((item) => {
      const matchesQuery = !needle || item.title.toLowerCase().includes(needle);
      const matchesTags = activeTags.every((tag) => item.tags.includes(tag));
      return matchesQuery && matchesTags;
    });
  }, [items, query, activeTags]);

  const toggleTag = (tag: string) => {
    setActiveTags((current) =>
      current.includes(tag) ? current.filter((t) => t !== tag) : [...current, tag],
    );
  };

  if (loading) return <p className="page">Загружаем сценарии…</p>;
  if (error) return <p className="page page--error">Не удалось загрузить сценарии: {error}</p>;

  return (
    <main className="page page--wide">
      <section className="card hero-card hero-card--compact">
        <span className="eyebrow">Библиотека</span>
        <h1>Сценарии</h1>
        <p className="lead">Выберите тренировку и пройдите её в диалоге с персонажем.</p>
      </section>

      <section className="scenario-filters">
        <input
          type="text"
          className="scenario-filters__search"
          placeholder="Поиск по названию…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label="Поиск сценариев по названию"
        />
        {allTags.length > 0 && (
          <div className="scenario-filters__tags">
            {allTags.map((tag) => (
              <button
                key={tag}
                type="button"
                className={`tag-chip${activeTags.includes(tag) ? ' tag-chip--active' : ''}`}
                onClick={() => toggleTag(tag)}
                aria-pressed={activeTags.includes(tag)}
              >
                {tag}
              </button>
            ))}
          </div>
        )}
      </section>

      {items.length === 0 && <p>Сценариев пока нет.</p>}
      {items.length > 0 && filtered.length === 0 && <p>Ничего не нашлось по этому фильтру.</p>}

      <section className="scenario-grid">
        {filtered.map((item) => (
          <Link
            key={item.id}
            className="product"
            to={`/scenarios/${item.id}`}
            aria-label={`Подробнее о «${item.title}»`}
          >
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
            {item.tags.length > 0 && (
              <div className="product-tags">
                {item.tags.map((tag) => (
                  <span key={tag} className="tag-chip">
                    {tag}
                  </span>
                ))}
              </div>
            )}
            <div className="product-foot">
              <span>{item.stages_count} этапа(ов)</span>
              <span className="arrow-btn" aria-hidden="true">
                <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4.5 12h14" />
                  <path d="m12.5 6 6 6-6 6" />
                </svg>
              </span>
            </div>
          </Link>
        ))}
      </section>

      {/* TODO: редактор сценария (§7) — правка полей персонажа, этапов и рубрики,
          плюс копирование шаблона перед правкой. */}
    </main>
  );
}
