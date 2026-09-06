import { describe, expect, it } from 'vitest';

import type { SubtitleEvent } from '@/contracts/events';

import { currentCueSentence, joinCueText } from './cueText';

function cue(text: string, start_ms = 0): SubtitleEvent {
  return { type: 'subtitle', gen_id: 1, text, start_ms, end_ms: start_ms + 100 };
}

describe('текст timestamp-субтитров', () => {
  it('не вставляет пробелы между частями одного слова', () => {
    expect(joinCueText([cue('При'), cue('вет'), cue(', '), cue('мир')])).toBe('Привет, мир');
  });

  it('разделяет старые цельные предложения', () => {
    expect(joinCueText([cue('Первое.'), cue('Второе.')])).toBe('Первое. Второе.');
  });

  it('оставляет в оверлее текущую фразу', () => {
    expect(currentCueSentence('Первая фраза. Вторая ещё продолжается')).toBe(
      'Вторая ещё продолжается',
    );
    expect(currentCueSentence('Первая фраза. Вторая закончилась.')).toBe('Вторая закончилась.');
  });
});
