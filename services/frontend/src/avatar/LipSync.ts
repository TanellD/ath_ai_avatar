/**
 * Липсинк — Claude.md §3, §8, метрика 2.
 *
 * Кадры мимики берут время ТОЛЬКО из PlaybackClock, то есть из фактически
 * воспроизводимого аудио. Ни setInterval, ни requestAnimationFrame-счётчика,
 * ни Date.now(). ESLint это проверяет (см. .eslintrc.cjs) — не потому что
 * правило красивое, а потому что нарушение выглядит рабочим и проявляется
 * только на защите.
 *
 * requestAnimationFrame здесь используется как источник *кадров рендера*, а не
 * как источник *времени*: каждый кадр спрашивает у часов текущую позицию.
 * Это принципиально разные роли, и путать их нельзя.
 */

import type { PlaybackClock } from '@/audio/PlaybackClock';

/**
 * Асимметричный допуск из ITU-R BT.1359 (Claude.md §9).
 *
 * Опережение звука заметно примерно вдвое раньше отставания, поэтому лучше
 * отдать лицо чуть раньше звука, чем позже.
 */
export const LIPSYNC_LEAD_MS = 40;

export interface FaceFrame {
  /** Раскрытие рта 0..1. */
  openness: number;
  positionMs: number;
}

export type FaceRenderer = (frame: FaceFrame) => void;

export class LipSync {
  private readonly clock: PlaybackClock;
  private readonly render: FaceRenderer;
  private rafId: number | null = null;

  constructor(clock: PlaybackClock, render: FaceRenderer) {
    this.clock = clock;
    this.render = render;
  }

  start(): void {
    if (this.rafId !== null) return;

    const tick = () => {
      // Время — у часов, не у rAF. Это и есть смысл всего файла.
      const positionMs = this.clock.positionMs() + LIPSYNC_LEAD_MS;

      this.render({
        openness: this.clock.isPlaying ? this.opennessAt(positionMs) : 0,
        positionMs,
      });

      this.rafId = requestAnimationFrame(tick);
    };

    this.rafId = requestAnimationFrame(tick);
  }

  stop(): void {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    // Рот не должен замереть открытым — это единственное, что зритель
    // безошибочно считывает как «сломалось».
    this.render({ openness: 0, positionMs: 0 });
  }

  /**
   * Раскрытие рта в заданный момент.
   *
   * TODO: сейчас заглушка. Настоящая реализация зависит от рендера:
   *  - при Simli (§10) визем не считаем вообще — туда уходит аудио, оттуда
   *    приходит видео, и этот класс сводится к синхронизации кадров по часам;
   *  - при запасном локальном рендере — амплитудная огибающая из AnalyserNode
   *    поверх того же AudioContext.
   *
   * Важно: при деградации сети лицо замирает, а голос продолжается (§8).
   * Не наоборот — рассинхрон заметнее паузы.
   */
  private opennessAt(_positionMs: number): number {
    return 0;
  }
}
