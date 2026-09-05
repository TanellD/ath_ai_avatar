/**
 * Очередь аудио-чанков одного поколения — Claude.md §6.
 *
 * Второй рубеж инварианта «после отмены ни один чанк старого поколения не
 * воспроизводится» (метрика 4 = 0). Первый стоит на сервере
 * (GenerationRegistry.is_stale), но полагаться на одну сторону нельзя: чанк
 * мог уже уйти в сокет до отмены и прилететь сюда после неё.
 *
 * Правило простое и без исключений: **чанк с gen_id != currentGeneration не
 * планируется.** Не «планируется потише», не «планируется, если уже начал
 * играть» — просто отбрасывается.
 */

export interface QueuedChunk {
  genId: number;
  seq: number;
  /** base64 содержимое из события audio_chunk. */
  data: string;
}

function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

export class AudioQueue {
  private readonly context: AudioContext;
  private readonly clock: import('./PlaybackClock').PlaybackClock;
  private readonly gain: GainNode;
  private readonly compressor: DynamicsCompressorNode;

  private currentGeneration = 0;

  /** Активные источники текущего поколения — их надо уметь остановить мгновенно. */
  private sources = new Set<AudioBufferSourceNode>();

  /**
   * Декодирование асинхронно, а поколение за это время может смениться.
   * Считаем, сколько декодирований в полёте, чтобы понимать состояние очереди.
   */
  private decoding = 0;

  /**
   * WebSocket сохраняет порядок кадров, но decodeAudioData завершается
   * недетерминированно. Цепочка не позволяет более позднему seq попасть в
   * расписание раньше предыдущего и вызвать перестановку/икание аудио.
   */
  private schedulingTail: Promise<void> = Promise.resolve();

  /**
   * Вызывается, когда очередь становится пустой — естественным завершением
   * воспроизведения (последний source доиграл) либо отменой (stopAll).
   * Единственный источник правды для UI-индикатора «персонаж говорит»: он
   * обязан гаснуть по факту тишины, а не по серверным событиям (`action`
   * приходит, когда байты ОТПРАВЛЕНЫ, а не когда они доиграли).
   */
  private readonly onIdle?: () => void;
  private readonly onFirstAudioScheduled?: (genId: number, leadMs: number) => void;
  private firstAudioReported = false;

  /**
   * @param destination Куда подключать декодированные источники. По умолчанию
   *   динамики (`context.destination`). При рендере через TalkingHead сюда
   *   передают `head.audioSpeechGainNode` — тогда HeadAudio, подключенный к
   *   тому же узлу выше по графу, видит реально проигрываемый звук и ведёт
   *   визему от него, а не от отдельного таймера (Claude.md §3).
   */
  constructor(
    context: AudioContext,
    clock: import('./PlaybackClock').PlaybackClock,
    destination?: AudioNode,
    onIdle?: () => void,
    onFirstAudioScheduled?: (genId: number, leadMs: number) => void,
  ) {
    this.context = context;
    this.clock = clock;
    this.gain = context.createGain();
    this.compressor = context.createDynamicsCompressor();
    // Мягко прижимаем только заметно более громкие фрагменты Soniox. Один
    // постоянный узел на всю сессию сохраняет интонацию внутри реплики и не
    // создаёт скачка на границе аудиочанков.
    this.compressor.threshold.value = -22;
    this.compressor.knee.value = 14;
    this.compressor.ratio.value = 3;
    this.compressor.attack.value = 0.008;
    this.compressor.release.value = 0.2;
    this.gain.connect(this.compressor);
    this.compressor.connect(destination ?? context.destination);
    this.onIdle = onIdle;
    this.onFirstAudioScheduled = onFirstAudioScheduled;
  }

  get generation(): number {
    return this.currentGeneration;
  }

  get isIdle(): boolean {
    return this.sources.size === 0 && this.decoding === 0;
  }

  /**
   * Перейти на новое поколение.
   *
   * Вызывать ДО того, как придёт первый чанк нового поколения, — иначе он
   * будет отброшен как чужой.
   */
  startGeneration(genId: number): void {
    this.currentGeneration = genId;
    this.firstAudioReported = false;
  }

  /**
   * Принять чанк и запланировать его воспроизведение.
   *
   * Проверка поколения делается дважды: до декодирования и после. Декодирование
   * занимает единицы миллисекунд, но перебивание может случиться ровно в этот
   * промежуток — и тогда без второй проверки хвост всё-таки прозвучит.
   */
  enqueue(chunk: QueuedChunk): Promise<void> {
    const scheduled = this.schedulingTail.then(() => this.decodeAndSchedule(chunk));
    this.schedulingTail = scheduled;
    return scheduled;
  }

  private async decodeAndSchedule(chunk: QueuedChunk): Promise<void> {
    if (chunk.genId !== this.currentGeneration) return;

    this.decoding += 1;
    try {
      const buffer = await this.context.decodeAudioData(base64ToArrayBuffer(chunk.data));

      if (chunk.genId !== this.currentGeneration) return;

      const source = this.context.createBufferSource();
      source.buffer = buffer;
      source.connect(this.gain);

      const startAt = this.clock.nextStartTime();
      source.start(startAt);
      this.clock.noteScheduled(startAt, buffer.duration);
      if (!this.firstAudioReported) {
        this.firstAudioReported = true;
        const leadMs = Math.max(0, (startAt - this.context.currentTime) * 1000);
        this.onFirstAudioScheduled?.(chunk.genId, leadMs);
      }

      this.sources.add(source);
      source.onended = () => {
        this.sources.delete(source);
        // Естественный конец речи: последний source этого поколения доиграл
        // и в полёте больше ничего не декодируется — тишина наступила по-настоящему.
        if (this.isIdle) this.onIdle?.();
      };
    } catch (error) {
      // Битый чанк не должен ронять сессию: один пропущенный кусок звука
      // переживаем, оборванный диалог — нет.
      console.error('[audio] failed to decode chunk', chunk.seq, error);
    } finally {
      this.decoding -= 1;
    }
  }

  /**
   * Мгновенная остановка. Бюджет — менее 20 мс (Claude.md §9).
   *
   * Синхронная целиком: никаких await, никаких сетевых обращений. Это половина
   * метрики 3, и она обязана выполниться до того, как браузер отрисует
   * следующий кадр.
   */
  stopAll(): void {
    for (const source of this.sources) {
      try {
        source.onended = null;
        source.stop();
        source.disconnect();
      } catch {
        // Источник мог завершиться сам между итерацией и вызовом stop().
      }
    }
    this.sources.clear();
    this.clock.reset();
    this.firstAudioReported = false;
    this.onIdle?.();
  }
}
