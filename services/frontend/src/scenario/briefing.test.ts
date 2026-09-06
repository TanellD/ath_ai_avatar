/**
 * Шаблон подстановки обязан совпадать с питоновским `render_text`: разойдясь,
 * стороны подставят разное, и сотрудник увидит фигурные скобки в тексте.
 */

import { describe, expect, test } from 'vitest';

import type { ScenarioSlot } from '@/contracts/events';

import { renderBriefing, slotDefaults } from './briefing';

const SLOTS: ScenarioSlot[] = [
  { id: 'company', label: 'Компания', hint: 'закупщик', example: 'Северный Ветер' },
  { id: 'product', label: 'Продукт', hint: 'что продаём', example: 'CRM' },
];

describe('renderBriefing', () => {
  test('подставляет объявленные слоты', () => {
    const text = renderBriefing('Вы продаёте {product} компании «{company}».', {
      company: 'Северный Ветер',
      product: 'CRM',
    });

    expect(text).toBe('Вы продаёте CRM компании «Северный Ветер».');
  });

  test('один слот подставляется во все свои вхождения', () => {
    expect(renderBriefing('{company} и ещё раз {company}', { company: 'X' })).toBe(
      'X и ещё раз X',
    );
  });

  test('неизвестный плейсхолдер остаётся видимым, а не стирается', () => {
    // Пустое место в тексте не отличить от задумки; «{company}» видно глазами.
    expect(renderBriefing('Клиент — {company}.', {})).toBe('Клиент — {company}.');
  });

  test('одинокая скобка в тексте методиста не ломает подстановку', () => {
    expect(renderBriefing('Скидка 20% {и ещё {company}', { company: 'X' })).toBe(
      'Скидка 20% {и ещё X',
    );
  });

  test('текст без подстановок возвращается как есть', () => {
    expect(renderBriefing('Обычный бриф без слотов.', SLOTS.length ? {} : {})).toBe(
      'Обычный бриф без слотов.',
    );
  });
});

describe('slotDefaults', () => {
  test('примеры методиста — это и есть значения для превью', () => {
    expect(slotDefaults(SLOTS)).toEqual({ company: 'Северный Ветер', product: 'CRM' });
  });

  test('сценарий без слотов даёт пустую подстановку', () => {
    expect(slotDefaults([])).toEqual({});
  });
});
