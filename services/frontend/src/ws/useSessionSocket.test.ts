/**
 * Инвариант §6, шаг 7: до UI не доходит ни одно событие чужого поколения.
 * Второй рубеж после серверного GenerationRegistry.is_stale.
 */

import { describe, expect, it } from 'vitest';

import type { ServerEvent } from '@/contracts/events';

import { isStaleEvent } from './useSessionSocket';

const chunk = (genId: number): ServerEvent => ({
  type: 'audio_chunk',
  gen_id: genId,
  seq: 0,
  data: '',
  format: 'wav',
  emotion: 'neutral',
});

describe('isStaleEvent', () => {
  it('пропускает событие текущего поколения', () => {
    expect(isStaleEvent(chunk(4), 4)).toBe(false);
  });

  it('отбрасывает отставшее поколение', () => {
    expect(isStaleEvent(chunk(3), 4)).toBe(true);
  });

  it('отбрасывает и опередившее поколение', () => {
    // Клиент ведёт счётчик зеркально; расхождение в любую сторону означает,
    // что событие относится не к тому ходу, который сейчас на экране.
    expect(isStaleEvent(chunk(5), 4)).toBe(true);
  });

  it('пропускает cancel чужого поколения', () => {
    // Отмена по определению говорит о поколении, которое уже не текущее.
    // Отбросить её — значит не узнать об отмене вовсе.
    expect(isStaleEvent({ type: 'cancel', gen_id: 3 }, 4)).toBe(false);
  });

  it('пропускает ошибку без поколения', () => {
    const event: ServerEvent = {
      type: 'error',
      gen_id: null,
      code: 'stt_internal',
      message: 'x',
      spoken: false,
    };
    expect(isStaleEvent(event, 4)).toBe(false);
  });

  it('пропускает ошибку чужого поколения', () => {
    // gen_id ошибки может отставать от текущего (например, отмена сама и
    // вызвала ошибку) — отбросить её значит оставить пользователя без
    // единственного сигнала о сбое.
    const event: ServerEvent = {
      type: 'error',
      gen_id: 3,
      code: 'voice_capture_active',
      message: 'x',
      spoken: false,
    };
    expect(isStaleEvent(event, 4)).toBe(false);
  });

  it('отбрасывает транскрипт отменённого хода', () => {
    const event: ServerEvent = {
      type: 'transcript',
      gen_id: 2,
      capture_id: 'c',
      provider_epoch: 0,
      provider: 'soniox',
      text: 'протухший текст',
      is_final: true,
      stt_confidence: null,
    };
    expect(isStaleEvent(event, 4)).toBe(true);
  });
});
