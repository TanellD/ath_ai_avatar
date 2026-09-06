/**
 * Проверяется то, что легко сломать незаметно: `applyDraft` не должен трогать
 * уже заполненный `id` (и никогда не трогает `brief`), но обязан подставить
 * предложенный id, пока поле пустое; `draftContext`/`isBlank` не должны
 * путать заготовку пустой формы с реальным содержимым (см. шапку draft.ts).
 */

import { describe, expect, test } from 'vitest';

import type { ScenarioDraft } from '@/api/client';
import type { Scenario } from '@/contracts/events';

import { applyDraft, draftContext, isBlank } from './draft';

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
    brief: 'Продажа CRM закупщику, который считает, что бюджета нет',
    briefing: '',
    slots: [],
    ...patch,
  };
}

function blankScenario(): Scenario {
  return scenario({
    id: '',
    title: '',
    persona: {
      name: '',
      role: '',
      character: '',
      mood: 'neutral',
      difficulty: 3,
      voice_id: null,
      holds_initiative: true,
    },
    stages: [
      { id: 'stage_1', goal: '', agent_opening: '', completion_criteria: '', max_turns: 4 },
    ],
    rubric: [{ id: 'criterion_1', name: '', description: '', scale: 5, weight: 1 }],
    tags: [],
    brief: '',
    briefing: '',
  });
}

function draft(patch: Partial<ScenarioDraft> = {}): ScenarioDraft {
  return {
    title: 'Другой сценарий',
    suggested_id: 'crm_pitch',
    persona: {
      name: 'Пётр',
      role: 'начальник отдела закупок',
      character: 'прямолинеен',
      mood: 'irritated',
      difficulty: 4,
      voice_id: null,
      holds_initiative: true,
    },
    stages: [
      {
        id: 'discovery',
        goal: 'Выяснить потребность',
        agent_opening: 'Слушаю вас.',
        completion_criteria: 'Задан открытый вопрос',
        max_turns: 3,
      },
    ],
    rubric: [
      { id: 'discovery', name: 'Выявление потребности', description: 'Открытые вопросы', scale: 5, weight: 1 },
    ],
    tags: ['crm'],
    briefing: 'Вы продаёте {product} компании {company}.',
    slots: [
      { id: 'product', label: 'Продукт', hint: 'что продаём', example: 'CRM' },
      { id: 'company', label: 'Компания', hint: 'кто покупает', example: 'Северный Ветер' },
    ],
    ...patch,
  };
}

describe('applyDraft', () => {
  test('заменяет содержимое формы черновиком', () => {
    const applied = applyDraft(scenario(), draft());

    expect(applied.title).toBe('Другой сценарий');
    expect(applied.persona).toEqual(draft().persona);
    expect(applied.stages).toEqual(draft().stages);
    expect(applied.rubric).toEqual(draft().rubric);
    expect(applied.tags).toEqual(draft().tags);
    expect(applied.briefing).toBe(draft().briefing);
    expect(applied.slots).toEqual(draft().slots);
  });

  test('не трогает уже заполненный id — его задаёт человек, он же адрес страницы', () => {
    const applied = applyDraft(scenario({ id: 'my_scenario' }), draft());

    expect(applied.id).toBe('my_scenario');
  });

  test('подставляет предложенный id, пока поле пустое', () => {
    const applied = applyDraft(scenario({ id: '' }), draft({ suggested_id: 'price_objection' }));

    expect(applied.id).toBe('price_objection');
  });

  test('пустой id остаётся пустым, если предложить нечего', () => {
    const applied = applyDraft(scenario({ id: '' }), draft({ suggested_id: undefined }));

    expect(applied.id).toBe('');
  });

  test('не трогает brief — это вход генерации, а не её результат', () => {
    const applied = applyDraft(scenario({ brief: 'Исходное описание методиста' }), draft());

    expect(applied.brief).toBe('Исходное описание методиста');
  });
});

describe('isBlank', () => {
  test('пустая заготовка формы — blank', () => {
    expect(isBlank(blankScenario())).toBe(true);
  });

  test('заполненное название снимает blank', () => {
    expect(isBlank(blankScenario())).toBe(true);
    expect(isBlank({ ...blankScenario(), title: 'Что-то' })).toBe(false);
  });

  test('заполненный персонаж снимает blank', () => {
    const filled = blankScenario();
    filled.persona.name = 'Ирина';
    expect(isBlank(filled)).toBe(false);
  });

  test('заполненный этап снимает blank', () => {
    const filled = blankScenario();
    filled.stages[0].goal = 'Установить контакт';
    expect(isBlank(filled)).toBe(false);
  });
});

describe('draftContext', () => {
  test('null на пустой форме — генерации не на что опираться', () => {
    expect(draftContext(blankScenario())).toBeNull();
  });

  test('заполненная форма уходит как контекст целиком', () => {
    const context = draftContext(scenario());

    expect(context).not.toBeNull();
    expect(context?.title).toBe(scenario().title);
    expect(context?.persona).toEqual(scenario().persona);
  });

  test('id, brief и suggested_id в контекст не попадают', () => {
    const context = draftContext(scenario());

    expect(context).not.toHaveProperty('id');
    expect(context).not.toHaveProperty('brief');
    expect(context).not.toHaveProperty('suggested_id');
  });
});
