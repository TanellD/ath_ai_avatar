/**
 * Карточка кейса перед запуском — docs/bugs_front.md №8.
 *
 * Раньше карточка на /scenarios вела сразу в сессию: сотрудник не видел,
 * что вообще будет проверяться. Показываем персонажа, цель каждого этапа
 * и то, что оценивается по рубрике — «что проверяется, что ожидается» из
 * формулировки бага.
 *
 * `stage.completion_criteria` сюда осознанно не идёт — тот же принцип, что
 * и в подсказке по этапу (StageHint.tsx) и в промпте персонажа (Claude.md
 * §5): это точная формулировка для классификатора, а не то, что должен
 * знать сотрудник заранее. Цель этапа (`goal`) и описание критерия рубрики
 * (`rubric[].description`) — совсем другое: это ответ на «что вообще здесь
 * происходит», а не шпаргалка с правильными фразами.
 */

import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { scenarioApi } from '@/api/client';
import { AVATAR_MODEL_LIST } from '@/avatar/TalkingHeadAvatar';
import { ScenarioBriefing } from '@/components/ScenarioBriefing';
import type { Scenario } from '@/contracts/events';
import { renderBriefing, slotDefaults } from '@/scenario/briefing';

export function ScenarioPreview() {
  const { scenarioId = '' } = useParams();
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [avatarId, setAvatarId] = useState(AVATAR_MODEL_LIST[0].id);

  useEffect(() => {
    scenarioApi
      .get(scenarioId)
      .then(setScenario)
      .catch((cause: Error) => setError(cause.message));
  }, [scenarioId]);

  if (error) return <p className="page page--error">Не удалось загрузить сценарий: {error}</p>;
  if (!scenario) return <p className="page">Загружаем сценарий…</p>;

  return (
    <main className="page page--wide">
      <section className="card hero-card">
        <span className="eyebrow">Кейс</span>
        <h1>{scenario.title}</h1>
        <p className="lead">
          {scenario.persona.name} — {scenario.persona.role}. {scenario.persona.character}.
        </p>
      </section>

      {/* Бриф с примерами методиста, без запроса к модели: «что это за кейс» —
          не повод ждать и платить. Детали конкретного прогона подставятся при
          старте тренировки, и там же сотрудник их и прочитает. */}
      {scenario.briefing && (
        <section className="card report__section">
          <span className="eyebrow">Обстановка</span>
          <h2>С чем вы придёте в разговор</h2>
          <ScenarioBriefing
            text={renderBriefing(scenario.briefing, slotDefaults(scenario.slots))}
          />
          {scenario.slots.length > 0 && (
            <p className="admin__hint">
              Имена, названия и цифры в тренировке будут другими — они подбираются заново
              на каждый прогон.
            </p>
          )}
        </section>
      )}

      <section className="card report__section">
        <span className="eyebrow">Этапы</span>
        <h2>Как строится разговор</h2>
        <ol className="scenario-preview__stages">
          {scenario.stages.map((stage, i) => (
            <li key={stage.id} className="scenario-preview__stage">
              <span className="bento-pill">{i + 1}</span>
              <p>{stage.goal}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="card report__section">
        <span className="eyebrow">Оценка</span>
        <h2>Что проверяется</h2>
        <ul className="scenario-preview__rubric">
          {scenario.rubric.map((item) => (
            <li key={item.id} className="scenario-preview__rubric-item">
              <h3>{item.name}</h3>
              <p>{item.description}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="card report__section">
        <span className="eyebrow">Персонаж</span>
        <h2>Кто будет разговаривать</h2>
        <div className="avatar-picker">
          {AVATAR_MODEL_LIST.map((model) => (
            <button
              key={model.id}
              type="button"
              className={`tag-chip${model.id === avatarId ? ' tag-chip--active' : ''}`}
              aria-pressed={model.id === avatarId}
              onClick={() => setAvatarId(model.id)}
            >
              {model.label}
            </button>
          ))}
        </div>
      </section>

      <div className="scenario-preview__actions">
        <Link to="/scenarios" className="btn btn-gray">
          Назад к списку
        </Link>
        <Link to={`/session/${scenario.id}?avatar=${avatarId}`} className="btn btn-primary">
          Начать тренировку
        </Link>
      </div>
    </main>
  );
}
