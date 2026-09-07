/**
 * Живой баг: в редакторе сценария нельзя было ввести теги через запятую.
 * Запятая исчезала в тот же момент, когда её набирали.
 */

import { describe, expect, test } from 'vitest';

import { formatTags, parseTags, tagsTextMatches } from './tags';

describe('parseTags', () => {
  test('разбирает список через запятую', () => {
    expect(parseTags('продажи, возражения, цена')).toEqual(['продажи', 'возражения', 'цена']);
  });

  test('не считает тегом пустоту между запятыми', () => {
    expect(parseTags('продажи,, цена')).toEqual(['продажи', 'цена']);
    expect(parseTags('   ')).toEqual([]);
  });
});

describe('tagsTextMatches', () => {
  test('незаконченный ввод считается СВОИМ и не переписывается', () => {
    // Ровно тот момент, когда старая форма съедала запятую: пользователь
    // набрал «продажи,» и собирается писать второй тег.
    expect(tagsTextMatches('продажи,', ['продажи'])).toBe(true);
    expect(tagsTextMatches('продажи, ', ['продажи'])).toBe(true);
  });

  test('внешнее изменение видно и строку надо пересобрать', () => {
    expect(tagsTextMatches('продажи', ['продажи', 'цена'])).toBe(false);
    expect(tagsTextMatches('', ['продажи'])).toBe(false);
  });

  test('порядок тегов важен', () => {
    expect(tagsTextMatches('цена, продажи', ['продажи', 'цена'])).toBe(false);
  });
});

describe('formatTags', () => {
  test('собирает строку для поля', () => {
    expect(formatTags(['продажи', 'цена'])).toBe('продажи, цена');
  });
});
