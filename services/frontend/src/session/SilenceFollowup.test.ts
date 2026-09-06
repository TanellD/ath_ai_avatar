import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SilenceFollowup, type SilencePhase } from './SilenceFollowup';

describe('SilenceFollowup', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
  });

  afterEach(() => vi.useRealTimers());

  it('напоминает на 10-й секунде и продолжает на 20-й', () => {
    const phases: SilencePhase[] = [];
    const followup = new SilenceFollowup((phase) => phases.push(phase));

    followup.resume();
    vi.advanceTimersByTime(10_000);
    expect(phases).toEqual(['nudge']);

    // Пока агент произносил напоминание, отсчёт был на паузе. После его
    // окончания сохраняется исходный дедлайн 20 секунд.
    followup.resume();
    vi.advanceTimersByTime(10_000);
    expect(phases).toEqual(['nudge', 'continue']);

    followup.resume();
    vi.advanceTimersByTime(60_000);
    expect(phases).toEqual(['nudge', 'continue']);
  });

  it('набор текста откладывает оба шага', () => {
    const phases: SilencePhase[] = [];
    const followup = new SilenceFollowup((phase) => phases.push(phase));

    followup.resume();
    vi.advanceTimersByTime(9_000);
    followup.postpone();
    vi.advanceTimersByTime(9_999);
    expect(phases).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(phases).toEqual(['nudge']);
  });

  it('начало голосового или текстового хода отменяет текущий цикл', () => {
    const phases: SilencePhase[] = [];
    const followup = new SilenceFollowup((phase) => phases.push(phase));

    followup.resume();
    vi.advanceTimersByTime(9_000);
    followup.beginUserTurn();
    vi.advanceTimersByTime(30_000);
    expect(phases).toEqual([]);

    followup.resume();
    vi.advanceTimersByTime(10_000);
    expect(phases).toEqual(['nudge']);
  });

  it('не считает набор текста во время речи агента началом тишины', () => {
    const phases: SilencePhase[] = [];
    const followup = new SilenceFollowup((phase) => phases.push(phase));

    followup.postpone();
    vi.advanceTimersByTime(30_000);
    followup.resume();
    vi.advanceTimersByTime(9_999);
    expect(phases).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(phases).toEqual(['nudge']);
  });
});
