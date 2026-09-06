export type SilencePhase = 'nudge' | 'continue';

// Раньше было 10_000 / 20_000 — подтверждённая жалоба пользователя «пишет
// слишком часто, раз в 5 секунд». Живой прогон (interview_junior, 90 с
// молчания) показал: бесконечного цикла нет, ровно два шага и тишина — но
// 10 с от конца обычной реплики персонажа слишком мало, чтобы человек успел
// прочитать её и начать печатать ответ, прежде чем персонаж уже подталкивает
// снова. Оба порога удвоены; anchor у обоих один и тот же (см. докстринг
// класса ниже), поэтому continue по-прежнему не «плюс 40 с после nudge», а
// «плюс 40 с после конца реплики» — вдвое больше в тех же пропорциях.
const NUDGE_MS = 20_000;
const CONTINUE_MS = 40_000;

/** Два одноразовых шага инициативы, отсчитанных от конца обычной реплики. */
export class SilenceFollowup {
  private timer: ReturnType<typeof setTimeout> | undefined;
  private anchor: number | undefined;
  private phase: 0 | 1 | 2 = 0;
  private waiting = false;

  constructor(
    private readonly onTimeout: (phase: SilencePhase) => void,
    private readonly now: () => number = Date.now,
  ) {}

  resume(): void {
    this.waiting = true;
    if (this.phase === 2) return;
    if (this.anchor === undefined) this.anchor = this.now();
    this.schedule();
  }

  pause(): void {
    this.waiting = false;
    this.clear();
  }

  beginUserTurn(): void {
    this.pause();
    this.anchor = undefined;
    this.phase = 0;
  }

  postpone(): void {
    this.phase = 0;
    this.anchor = this.waiting ? this.now() : undefined;
    if (this.waiting) this.schedule();
  }

  stop(): void {
    this.pause();
    this.anchor = undefined;
    this.phase = 2;
  }

  private schedule(): void {
    this.clear();
    if (!this.waiting || this.anchor === undefined || this.phase === 2) return;
    const deadline = this.anchor + (this.phase === 0 ? NUDGE_MS : CONTINUE_MS);
    this.timer = setTimeout(() => this.fire(), Math.max(0, deadline - this.now()));
  }

  private fire(): void {
    if (!this.waiting) return;
    this.waiting = false;
    this.timer = undefined;
    const next = this.phase === 0 ? 'nudge' : 'continue';
    this.phase = this.phase === 0 ? 1 : 2;
    this.onTimeout(next);
  }

  private clear(): void {
    if (this.timer !== undefined) clearTimeout(this.timer);
    this.timer = undefined;
  }
}
