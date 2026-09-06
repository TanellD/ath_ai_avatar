/**
 * Проверяется не полнота списка правил, а те случаи, которые backend
 * пропускает и которые ломают продукт молча (см. шапку validate.ts).
 */

import { describe, expect, test } from 'vitest';

import type { Scenario } from '@/contracts/events';

import { hasIssues, validateScenario } from './validate';

function scenario(patch: Partial<Scenario> = {}): Scenario {
  return {
    id: 'objection_price',
    title: 'Отработка возражения «дорого»',
    persona: {
      name: 'Ирина',
      role: 'закупщик среднего бизнеса',
      character: 'скептична, перебивает, торгуется',
      mood: 'neutral',
      difficulty: 3,
      voice_id: null,
      holds_initiative: true,
    },
    stages: [
      {
        id: 'opening',
        goal: 'Установить контакт',
        agent_opening: 'Здравствуйте. У меня десять минут.',
        completion_criteria: 'Сотрудник представился',
        max_turns: 4,
      },
    ],
    rubric: [
      {
        id: 'discovery',
        name: 'Выявление потребности',
        description: 'Задавал открытые вопросы',
        scale: 5,
        weight: 1,
      },
    ],
    tags: ['продажи'],
    brief: '',
    briefing: '',
    slots: [],
    ...patch,
  };
}

describe('validateScenario', () => {
  test('корректный сценарий не даёт замечаний', () => {
    expect(hasIssues(validateScenario(scenario()))).toBe(false);
  });

  test('занятый id ловится только здесь — PUT молча перезаписал бы чужой сценарий', () => {
    const issues = validateScenario(scenario(), { takenIds: ['objection_price'] });

    expect(issues.id).toContain('уже существует');
  });

  test('при правке существующего сценария список занятых id не передаётся', () => {
    expect(validateScenario(scenario()).id).toBeUndefined();
  });

  test('id вне допустимого набора символов отклоняется: он становится сегментом URL', () => {
    expect(validateScenario(scenario({ id: 'Возражение Цена' })).id).toBeDefined();
    expect(validateScenario(scenario({ id: 'objection price' })).id).toBeDefined();
    expect(validateScenario(scenario({ id: 'objection-price_2' })).id).toBeUndefined();
  });

  test('дубликат stage.id помечается на втором вхождении — StageMachine схлопнул бы словарь', () => {
    const stage = scenario().stages[0];
    const issues = validateScenario(
      scenario({ stages: [stage, { ...stage, goal: 'Другая цель' }] }),
    );

    expect(issues['stages.0.id']).toBeUndefined();
    expect(issues['stages.1.id']).toContain('уже есть выше');
  });

  test('дубликат rubric[].id ловится до сессии, а не после неё в report_builder', () => {
    const item = scenario().rubric[0];
    const issues = validateScenario(
      scenario({ rubric: [item, { ...item, name: 'Другое название' }] }),
    );

    expect(issues['rubric.1.id']).toContain('уже есть выше');
  });

  test('пустые строки не проходят, хотя контракт их принимает', () => {
    const issues = validateScenario(
      scenario({
        title: '   ',
        stages: [{ ...scenario().stages[0], goal: '' }],
      }),
    );

    expect(issues.title).toBeDefined();
    expect(issues['stages.0.goal']).toBeDefined();
  });

  test('числовые границы продублированы, чтобы не ловить 422 после заполнения формы', () => {
    const issues = validateScenario(
      scenario({
        persona: { ...scenario().persona, difficulty: 7 },
        stages: [{ ...scenario().stages[0], max_turns: 0 }],
        rubric: [{ ...scenario().rubric[0], scale: 1, weight: 0 }],
      }),
    );

    expect(issues['persona.difficulty']).toBeDefined();
    expect(issues['stages.0.max_turns']).toBeDefined();
    expect(issues['rubric.0.scale']).toBeDefined();
    expect(issues['rubric.0.weight']).toBeDefined();
  });

  test('пустые списки этапов и рубрики помечаются на самом списке', () => {
    const issues = validateScenario(scenario({ stages: [], rubric: [] }));

    expect(issues.stages).toBeDefined();
    expect(issues.rubric).toBeDefined();
  });
});
