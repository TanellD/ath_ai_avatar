/**
 * Живой баг: при долгом молчании сотрудника персонаж заговаривает сам
 * (SilenceFollowup), и это ВТОРАЯ его реплика подряд — реплики пользователя
 * между ними нет. Прежняя версия смотрела только на роль последней строки и
 * дописывала новый ответ в конец предыдущего; склеенный пузырь становился
 * «живым» в ChatPanel, а живой рисуется из cues, которые таймер молчания
 * только что очистил, — готовое сообщение на глазах пустело.
 */

import { describe, expect, test } from 'vitest';

import { appendAgentToken } from './agentLines';

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
