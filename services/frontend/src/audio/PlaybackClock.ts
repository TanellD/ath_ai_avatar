/**
 * Единственные часы системы — Claude.md §3.
 *
 *   «Источник времени для мимики — фактически воспроизводимое аудио, а не
 *    независимый таймер.»
 *
 * Мимика и субтитры спрашивают время ТОЛЬКО здесь. Причина не в чистоте
 * архитектуры: независимый таймер расходится с реальным воспроизведением на
 * каждой заминке сети или ресемплинге, и метрика 2 (смещение аудио и губ
 * ≤ 200 мс) проваливается незаметно — на глаз видно только то, что «губы
 * плывут», а искать источник расхождения в этот момент уже поздно.
 *
 * Порог метрики 2 асимметричен (ITU-R BT.1359): опережение звука заметно
 * примерно вдвое раньше отставания — не более 45 мс вперёд против 125 мс
 * назад. Поэтому при выборе, отдать кадр чуть раньше или чуть позже звука,
 * правильный ответ — раньше.
 */

export class PlaybackClock {
  private readonly context: AudioContext;

  /** Момент AudioContext, в который начало звучать текущее поколение. */
  private generationStartedAt: number | null = null;

  /** Момент, до которого уже запланировано аудио. Хвост очереди. */
  private scheduledUntil = 0;

  constructor(context: AudioContext) {
    this.context = context;
  }

  /** Время самого AudioContext. Монотонно, не зависит от вкладки и таймеров. */
  get contextTime(): number {
    return this.context.currentTime;
  }

  get isPlaying(): boolean {
    return this.generationStartedAt !== null && this.contextTime < this.scheduledUntil;
  }

  /**
   * Позиция внутри текущего ответа персонажа, в миллисекундах.
   *
   * Это и есть значение, от которого работают липсинк и субтитры. До первого
   * звука возвращает 0 — не отрицательное число и не «время с начала сессии».
   */
  positionMs(): number {
    if (this.generationStartedAt === null) return 0;
    return Math.max(0, (this.contextTime - this.generationStartedAt) * 1000);
  }

  /**
   * Куда планировать следующий чанк.
   *
   * Если очередь опустела (сеть моргнула), стартуем от «сейчас плюс небольшой
   * запас», а не от прошедшего момента — иначе браузер проиграет чанк мгновенно и
   * звук съедет вперёд относительно уже показанных кадров.
   */
  nextStartTime(minLeadSec = 0.02): number {
    const now = this.contextTime;
    return Math.max(this.scheduledUntil, now + minLeadSec);
  }

  /** Отметить, что чанк запланирован на [startAt, startAt + duration). */
  noteScheduled(startAt: number, durationSec: number): void {
    if (this.generationStartedAt === null) {
      this.generationStartedAt = startAt;
    }
    this.scheduledUntil = Math.max(this.scheduledUntil, startAt + durationSec);
  }

  /**
   * Сброс на новое поколение.
   *
   * Вызывается при перебивании: старая позиция не должна протекать в новый
   * ответ, иначе субтитры нового поколения стартуют с середины.
   */
  reset(): void {
    this.generationStartedAt = null;
    this.scheduledUntil = 0;
  }
}
