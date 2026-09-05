/**
 * Метрика 4 = 0: после отмены ни один чанк старого поколения не звучит.
 *
 * Проверка поколения в AudioQueue стоит дважды — до декодирования и после.
 * Вторая существует ровно ради случая, когда перебивание попадает в
 * промежуток, поэтому она проверяется отдельным тестом с управляемым
 * декодированием, а не «заодно».
 */

import { describe, expect, it, vi } from 'vitest';

import { AudioQueue } from './AudioQueue';
import type { PlaybackClock } from './PlaybackClock';

interface FakeSource {
  buffer: unknown;
  connect: () => void;
  start: (at: number) => void;
  stop: () => void;
  disconnect: () => void;
  onended: (() => void) | null;
}

function makeContext(decode: (data: ArrayBuffer) => Promise<{ duration: number }>) {
  const sources: FakeSource[] = [];
  const gain = { connect: vi.fn() };
  const compressor = {
    connect: vi.fn(),
    threshold: { value: 0 },
    knee: { value: 0 },
    ratio: { value: 0 },
    attack: { value: 0 },
    release: { value: 0 },
  };
  const context = {
    currentTime: 0,
    destination: {},
    createGain: () => gain,
    createDynamicsCompressor: () => compressor,
    decodeAudioData: vi.fn(decode),
    createBufferSource: () => {
      const source: FakeSource = {
        buffer: null,
        connect: vi.fn(),
        start: vi.fn(),
        stop: vi.fn(),
        disconnect: vi.fn(),
        onended: null,
      };
      sources.push(source);
      return source;
    },
  };
  return { context, sources, gain, compressor };
}

function makeClock() {
  return {
    nextStartTime: vi.fn(() => 0),
    noteScheduled: vi.fn(),
    reset: vi.fn(),
  };
}

function build(decode: (data: ArrayBuffer) => Promise<{ duration: number }>) {
  const { context, sources, gain, compressor } = makeContext(decode);
  const clock = makeClock();
  const queue = new AudioQueue(
    context as unknown as AudioContext,
    clock as unknown as PlaybackClock,
  );
  return { queue, sources, clock, context, gain, compressor };
}

const CHUNK = { genId: 1, seq: 0, data: btoa('fake-wav-bytes') };

/** enqueue ставит декодирование в микрозадачу — до неё проверять нечего. */
async function tick(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

describe('AudioQueue: защита от протухших чанков', () => {
  it('сглаживает пики одним компрессором на всю очередь', () => {
    const { context, gain, compressor } = build(async () => ({ duration: 0.1 }));

    expect(gain.connect).toHaveBeenCalledWith(compressor);
    expect(compressor.connect).toHaveBeenCalledWith(context.destination);
    expect(compressor.threshold.value).toBe(-22);
    expect(compressor.ratio.value).toBe(3);
  });

  it('не декодирует чанк чужого поколения', async () => {
    const { queue, context } = build(async () => ({ duration: 0.1 }));
    queue.startGeneration(2);

    await queue.enqueue({ ...CHUNK, genId: 1 });

    // Первый рубеж: до декодирования. Экономит и CPU, и — главное — не даёт
    // чанку шанса проскочить дальше.
    expect(context.decodeAudioData).not.toHaveBeenCalled();
  });

  it('отбрасывает чанк, протухший во время декодирования', async () => {
    let release: (buffer: { duration: number }) => void = () => {};
    const pending = new Promise<{ duration: number }>((resolve) => {
      release = resolve;
    });
    const { queue, sources } = build(() => pending);
    queue.startGeneration(1);

    const scheduled = queue.enqueue(CHUNK);
    // Перебивание попадает ровно в промежуток между началом и концом
    // декодирования — случай, ради которого существует вторая проверка.
    queue.startGeneration(2);
    release({ duration: 0.1 });
    await scheduled;

    expect(sources).toHaveLength(0);
  });

  it('планирует чанк своего поколения', async () => {
    const { queue, sources, clock } = build(async () => ({ duration: 0.1 }));
    queue.startGeneration(1);

    await queue.enqueue(CHUNK);

    expect(sources).toHaveLength(1);
    expect(sources[0].start).toHaveBeenCalled();
    expect(clock.noteScheduled).toHaveBeenCalledWith(0, 0.1);
  });

  it('stopAll глушит источники и сбрасывает часы', async () => {
    const { queue, sources, clock } = build(async () => ({ duration: 0.1 }));
    queue.startGeneration(1);
    await queue.enqueue(CHUNK);

    queue.stopAll();

    expect(sources[0].stop).toHaveBeenCalled();
    expect(sources[0].disconnect).toHaveBeenCalled();
    // onended снимается до stop(): иначе остановка выглядела бы как
    // естественное окончание речи и погасила бы индикатор не вовремя.
    expect(sources[0].onended).toBeNull();
    expect(clock.reset).toHaveBeenCalled();
    expect(queue.isIdle).toBe(true);
  });

  it('битый чанк не роняет очередь', async () => {
    const { queue, sources } = build(async () => {
      throw new Error('broken wav');
    });
    queue.startGeneration(1);

    await expect(queue.enqueue(CHUNK)).resolves.toBeUndefined();
    expect(sources).toHaveLength(0);
    // Один пропущенный кусок звука переживаем, оборванный диалог — нет.
    expect(queue.isIdle).toBe(true);
  });

  it('сохраняет порядок при разном времени декодирования', async () => {
    // Управляемые промисы вместо таймеров: в src/audio таймеры запрещены
    // правилом проекта, а тесту детерминированность нужнее задержек.
    const gates: Array<(buffer: { duration: number }) => void> = [];
    const { queue, sources } = build(
      () =>
        new Promise<{ duration: number }>((resolve) => {
          gates.push(resolve);
        }),
    );
    queue.startGeneration(1);

    const first = queue.enqueue({ ...CHUNK, seq: 0 });
    const second = queue.enqueue({ ...CHUNK, seq: 1 });
    await tick();

    // Первый чанк ещё декодируется, значит второй даже не начал: цепочка
    // планирования не пускает более поздний seq вперёд предыдущего.
    expect(gates).toHaveLength(1);

    gates[0]({ duration: 0.1 });
    await first;
    await tick();
    expect(gates).toHaveLength(2);

    gates[1]({ duration: 0.1 });
    await second;

    expect(sources).toHaveLength(2);
  });
});
