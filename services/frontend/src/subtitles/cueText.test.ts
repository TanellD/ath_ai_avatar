import { describe, expect, it } from 'vitest';

import type { SubtitleEvent } from '@/contracts/events';

import { SUBTITLE_LINGER_MS, currentCueSentence, joinCueText, subtitleAt } from './cueText';

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

describe('гашение субтитров', () => {
  it('показывает фразу, пока она звучит', () => {
    expect(subtitleAt([cue('Здравствуйте.', 0)], 50)).toBe('Здравствуйте.');
  });

  it('стирает текст, когда реплику сменили', () => {
    expect(subtitleAt([], 5000)).toBe('');
  });

  it('гасит фразу через секунду после конца ХОДА', () => {
    const line = [cue('Здравствуйте.', 0)]; // end_ms = 100
    expect(subtitleAt(line, 100 + SUBTITLE_LINGER_MS - 1, true)).toBe('Здравствуйте.');
    expect(subtitleAt(line, 100 + SUBTITLE_LINGER_MS + 1, true)).toBe('');
  });

  it('НЕ гасит в паузе посреди реплики, даже длинной', () => {
    // Регрессия, которую уже ловили живьём: TTS отдаёт речь чанками, пауза
    // между ними больше секунды, следующего cue ещё нет — и субтитры
    // пропадали прямо во время речи персонажа.
    const line = [cue('Здравствуйте.', 0)];
    expect(subtitleAt(line, 100 + SUBTITLE_LINGER_MS * 30)).toBe('Здравствуйте.');
  });
});
