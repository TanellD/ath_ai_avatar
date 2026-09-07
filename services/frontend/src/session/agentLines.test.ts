/**
 * Живой баг: при долгом молчании сотрудника персонаж заговаривает сам
 * (SilenceFollowup), и это ВТОРАЯ его реплика подряд — реплики пользователя
 * между ними нет. Прежняя версия смотрела только на роль последней строки и
 * дописывала новый ответ в конец предыдущего; склеенный пузырь становился
 * «живым» в ChatPanel, а живой рисуется из cues, которые таймер молчания
 * только что очистил, — готовое сообщение на глазах пустело.
 */

import { describe, expect, test } from 'vitest';

import { appendAgentToken, truncateLastAgentLine } from './agentLines';

describe('appendAgentToken', () => {
  test('токены одной реплики собираются в один пузырь', () => {
    let lines = appendAgentToken([], 'Здрав', true);
    lines = appendAgentToken(lines, 'ствуйте', true);

    expect(lines).toEqual([{ role: 'agent', text: 'Здравствуйте' }]);
  });

  test('новое поколение начинает новую реплику, а не продолжает прошлую', () => {
    const previous = [{ role: 'agent' as const, text: 'Слушаю вас.' }];

    const lines = appendAgentToken(previous, 'Вы ещё здесь?', false);

    expect(lines).toEqual([
      { role: 'agent', text: 'Слушаю вас.' },
      { role: 'agent', text: 'Вы ещё здесь?' },
    ]);
  });

  test('открытие нового этапа не склеивается с концом прошлой реплики', () => {
    // Переход этапа идёт тем же gen_id, поэтому `continues` по одному лишь
    // поколению был бы true — и в чате получалось слитное
    // «...частями?Я посмотрела ваш прайс...». Границу ставит обработчик
    // action: next_stage, обнуляя счёт реплики.
    const previous = [{ role: 'agent' as const, text: 'Возите частями?' }];

    const lines = appendAgentToken(previous, 'Я посмотрела ваш прайс.', false);

    expect(lines).toEqual([
      { role: 'agent', text: 'Возите частями?' },
      { role: 'agent', text: 'Я посмотрела ваш прайс.' },
    ]);
  });

  test('прошлая реплика сохраняет текст, когда персонаж говорит второй раз', () => {
    const previous = [{ role: 'agent' as const, text: 'Полный ответ персонажа.' }];

    const lines = appendAgentToken(previous, 'Продолжение?', false);

    expect(lines[0].text).toBe('Полный ответ персонажа.');
  });

  test('после реплики пользователя ответ всегда идёт новой строкой', () => {
    const history = [
      { role: 'agent' as const, text: 'Здравствуйте.' },
      { role: 'user' as const, text: 'Добрый день.' },
    ];

    const lines = appendAgentToken(history, 'Слушаю', true);

    expect(lines).toHaveLength(3);
    expect(lines[2]).toEqual({ role: 'agent', text: 'Слушаю' });
  });
});

describe('truncateLastAgentLine', () => {
  test('оставляет только произнесённое', () => {
    // Токены обгоняют звук: в пузыре уже вся фраза, а вслух прозвучала треть.
    const lines = [{ role: 'agent' as const, text: 'Здравствуйте, у меня десять минут.' }];

    expect(truncateLastAgentLine(lines, 'Здравствуйте, у меня')).toEqual([
      { role: 'agent', text: 'Здравствуйте, у меня' },
    ]);
  });

  test('убирает реплику, если персонаж не успел заговорить', () => {
    const lines = [
      { role: 'user' as const, text: 'Добрый день!' },
      { role: 'agent' as const, text: 'Здравствуйте' },
    ];

    expect(truncateLastAgentLine(lines, '')).toEqual([{ role: 'user', text: 'Добрый день!' }]);
  });

  test('не трогает реплику сотрудника', () => {
    const lines = [{ role: 'user' as const, text: 'Моя реплика' }];
    expect(truncateLastAgentLine(lines, 'Моя')).toEqual(lines);
  });

  test('не удлиняет реплику, если звук догнал текст', () => {
    const lines = [{ role: 'agent' as const, text: 'Коротко.' }];
    expect(truncateLastAgentLine(lines, 'Коротко.')).toEqual(lines);
  });
});
