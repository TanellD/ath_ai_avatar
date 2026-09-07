import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SilenceFollowup, type SilencePhase } from './SilenceFollowup';

describe('SilenceFollowup', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
  });

  afterEach(() => vi.useRealTimers());

  it('напоминает на 30-й секунде и продолжает ещё через 30 после неё', () => {
    const phases: SilencePhase[] = [];
    const followup = new SilenceFollowup((phase) => phases.push(phase));

    followup.resume();
    vi.advanceTimersByTime(30_000);
    expect(phases).toEqual(['nudge']);

    // Пока агент произносил напоминание, отсчёт был на паузе. resume() ниже
    // стартует НОВОЕ окно в 30 с — оно не наследует старый anchor.
    followup.resume();
    vi.advanceTimersByTime(30_000);
    expect(phases).toEqual(['nudge', 'continue']);

    followup.resume();
    vi.advanceTimersByTime(120_000);
    expect(phases).toEqual(['nudge', 'continue']);
  });

  it('озвучка nudge не крадёт время у окна ожидания continue', () => {
    // Живой баг: continue считался от anchor начала молчания, а не от конца
    // nudge — время генерации и озвучки самого nudge (LLM+TTS+сеть) вычиталось
    // из вторых 30 секунд. У разных людей эта задержка разная (сеть, нагрузка
    // TTS-воркера), поэтому баг был незаметен на быстром соединении и выглядел
    // как «продолжает почти сразу после nudge» на медленном.
    const phases: SilencePhase[] = [];
    const followup = new SilenceFollowup((phase) => phases.push(phase));

    followup.resume();
    vi.advanceTimersByTime(30_000);
    expect(phases).toEqual(['nudge']);

    // 10 секунд ушло на генерацию и проигрывание реплики-nudge — окно continue
    // обязано начаться заново именно с этого момента, а не быть урезанным.
    vi.advanceTimersByTime(10_000);
    followup.resume();
    vi.advanceTimersByTime(29_999);
    expect(phases).toEqual(['nudge']);
    vi.advanceTimersByTime(1);
    expect(phases).toEqual(['nudge', 'continue']);
  });

  it('набор текста откладывает оба шага', () => {
    const phases: SilencePhase[] = [];
    const followup = new SilenceFollowup((phase) => phases.push(phase));

    followup.resume();
    vi.advanceTimersByTime(29_000);
    followup.postpone();
    vi.advanceTimersByTime(29_999);
    expect(phases).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(phases).toEqual(['nudge']);
  });

  it('начало голосового или текстового хода отменяет текущий цикл', () => {
    const phases: SilencePhase[] = [];
    const followup = new SilenceFollowup((phase) => phases.push(phase));

    followup.resume();
    vi.advanceTimersByTime(29_000);
    followup.beginUserTurn();
    vi.advanceTimersByTime(50_000);
    expect(phases).toEqual([]);

    followup.resume();
    vi.advanceTimersByTime(30_000);
    expect(phases).toEqual(['nudge']);
  });

  it('не перебивает во время долгой паузы с непустым черновиком', () => {
    // Живой баг: пользователь формулирует длинный ответ, между нажатиями
    // клавиш пауза больше SILENCE_STEP_MS — раньше персонаж перебивал его прямо
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
    vi.advanceTimersByTime(29_999);
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
    vi.advanceTimersByTime(30_000);
    expect(phases).toEqual(['nudge']);
  });

  it('не считает набор текста во время речи агента началом тишины', () => {
    const phases: SilencePhase[] = [];
    const followup = new SilenceFollowup((phase) => phases.push(phase));

    followup.postpone();
    vi.advanceTimersByTime(50_000);
    followup.resume();
    vi.advanceTimersByTime(29_999);
    expect(phases).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(phases).toEqual(['nudge']);
  });
});
