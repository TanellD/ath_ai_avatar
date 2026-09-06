import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SilenceFollowup, type SilencePhase } from './SilenceFollowup';

describe('SilenceFollowup', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
  });

  afterEach(() => vi.useRealTimers());

  it('напоминает на 20-й секунде и продолжает на 40-й', () => {
    const phases: SilencePhase[] = [];
    const followup = new SilenceFollowup((phase) => phases.push(phase));

    followup.resume();
    vi.advanceTimersByTime(20_000);
    expect(phases).toEqual(['nudge']);

    // Пока агент произносил напоминание, отсчёт был на паузе. После его
    // окончания сохраняется исходный дедлайн 40 секунд.
    followup.resume();
    vi.advanceTimersByTime(20_000);
    expect(phases).toEqual(['nudge', 'continue']);

    followup.resume();
    vi.advanceTimersByTime(120_000);
    expect(phases).toEqual(['nudge', 'continue']);
  });

  it('набор текста откладывает оба шага', () => {
    const phases: SilencePhase[] = [];
    const followup = new SilenceFollowup((phase) => phases.push(phase));

    followup.resume();
    vi.advanceTimersByTime(19_000);
    followup.postpone();
    vi.advanceTimersByTime(19_999);
    expect(phases).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(phases).toEqual(['nudge']);
  });

  it('начало голосового или текстового хода отменяет текущий цикл', () => {
    const phases: SilencePhase[] = [];
    const followup = new SilenceFollowup((phase) => phases.push(phase));

    followup.resume();
    vi.advanceTimersByTime(19_000);
    followup.beginUserTurn();
    vi.advanceTimersByTime(50_000);
    expect(phases).toEqual([]);

    followup.resume();
    vi.advanceTimersByTime(20_000);
    expect(phases).toEqual(['nudge']);
  });

  it('не перебивает во время долгой паузы с непустым черновиком', () => {
    // Живой баг: пользователь формулирует длинный ответ, между нажатиями
    // клавиш пауза больше NUDGE_MS — раньше персонаж перебивал его прямо
    // посреди формулирования ответа, хотя поле ввода не пустое.
    const phases: SilencePhase[] = [];
    const followup = new SilenceFollowup((phase) => phases.push(phase));

    followup.resume();
    vi.advanceTimersByTime(5_000);
    followup.setDraftActive(true);
    vi.advanceTimersByTime(120_000);
    expect(phases).toEqual([]);

    // Стёр черновик, не отправив, — отсчёт стартует заново от этого момента.
    followup.setDraftActive(false);
    vi.advanceTimersByTime(19_999);
    expect(phases).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(phases).toEqual(['nudge']);
  });

  it('beginUserTurn сбрасывает черновик — следующее ожидание не блокируется навсегда', () => {
    const phases: SilencePhase[] = [];
    const followup = new SilenceFollowup((phase) => phases.push(phase));

    followup.resume();
    followup.setDraftActive(true);
    followup.beginUserTurn();

    followup.resume();
    vi.advanceTimersByTime(20_000);
    expect(phases).toEqual(['nudge']);
  });

  it('не считает набор текста во время речи агента началом тишины', () => {
    const phases: SilencePhase[] = [];
    const followup = new SilenceFollowup((phase) => phases.push(phase));

    followup.postpone();
    vi.advanceTimersByTime(50_000);
    followup.resume();
    vi.advanceTimersByTime(19_999);
    expect(phases).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(phases).toEqual(['nudge']);
  });
});
