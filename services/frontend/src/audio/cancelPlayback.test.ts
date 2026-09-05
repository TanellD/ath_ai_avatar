/**
 * Локальная остановка при перебивании — §6, шаг 1.
 *
 * Каждый «сток» проверяется отдельно: план требует, чтобы ни один потребитель
 * не остался с состоянием отменённого поколения. Забыть здесь один вызов —
 * значит получить замерший открытым рот или субтитры, продолжающие бежать
 * под тишину.
 */

import { describe, expect, it, vi } from 'vitest';

import type { AudioQueue } from './AudioQueue';
import { cancelPlayback } from './cancelPlayback';

function targets() {
  const calls: string[] = [];
  return {
    calls,
    queue: { stopAll: vi.fn(() => void calls.push('audio')) } as unknown as AudioQueue,
    freezeSubtitles: vi.fn(() => void calls.push('subtitles')),
    resetFace: vi.fn(() => void calls.push('face')),
  };
}

describe('cancelPlayback', () => {
  it('гасит все три стока', () => {
    const { queue, freezeSubtitles, resetFace } = targets();

    cancelPlayback({ queue, freezeSubtitles, resetFace });

    expect(queue.stopAll).toHaveBeenCalledOnce();
    expect(freezeSubtitles).toHaveBeenCalledOnce();
    expect(resetFace).toHaveBeenCalledOnce();
  });

  it('останавливает звук раньше визуального состояния', () => {
    const { calls, queue, freezeSubtitles, resetFace } = targets();

    cancelPlayback({ queue, freezeSubtitles, resetFace });

    // Пользователь замечает тишину раньше, чем положение губ: порядок здесь
    // часть бюджета в 300 мс, а не вкусовщина.
    expect(calls).toEqual(['audio', 'subtitles', 'face']);
  });

  it('работает синхронно', () => {
    const { calls, queue, freezeSubtitles, resetFace } = targets();

    const result = cancelPlayback({ queue, freezeSubtitles, resetFace });

    // Ни одного await: бюджет — менее 20 мс, любое ожидание сети превращает
    // их в 200.
    expect(result).toBeUndefined();
    expect(calls).toHaveLength(3);
  });
});
