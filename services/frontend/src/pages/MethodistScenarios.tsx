/**
 * Список сценариев — Claude.md §2, §11.
 *
 * Первый шаг демо: «методист выбирает шаблон, меняет два поля, запускает — за
 * минуту». Отсюда одно проектное решение: шаблон не редактируется на месте, а
 * копируется. Иначе первый же прогон испортит эталон для всей команды.
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
    <main className="page">
      <h1>Сценарии</h1>

      {items.length === 0 && <p>Сценариев пока нет.</p>}

      <ul className="scenarios">
        {items.map((item) => (
          <li key={item.id} className="scenarios__item">
            <div>
              <h2>{item.title}</h2>
              <p className="scenarios__meta">
                Персонаж: {item.persona_name} · этапов: {item.stages_count} · критериев:{' '}
                {item.rubric_count}
              </p>
            </div>
            <Link className="scenarios__start" to={`/session/${item.id}`}>
              Пройти
            </Link>
          </li>
        ))}
      </ul>

      {/* TODO: редактор сценария (§7) — правка полей персонажа, этапов и рубрики,
          плюс копирование шаблона перед правкой. */}
    </main>
  );
}
