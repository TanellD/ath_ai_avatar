/**
 * Оба обработчика ниже — про телефон по http. На десктопе разработчик всегда
 * на localhost, то есть в безопасном контексте, и ни одну из этих веток не
 * увидит ни разу.
 */

import { describe, expect, test } from 'vitest';

import { checkMicAvailability, randomUuid } from './secureContext';

type Scope = Parameters<typeof checkMicAvailability>[0];

function scope(patch: Partial<Scope> = {}): Scope {
  return {
    isSecureContext: true,
    navigator: { mediaDevices: { getUserMedia: () => Promise.resolve({}) } as MediaDevices },
    AudioWorkletNode: class {},
    ...patch,
  } as Scope;
}

describe('checkMicAvailability', () => {
  test('в безопасном контексте с поддержкой — доступен', () => {
    expect(checkMicAvailability(scope()).available).toBe(true);
  });

  test('без HTTPS объясняет про HTTPS, а не «браузер не поддерживает»', () => {
    // Прежний текст уводил в сторону: браузер поддерживает, не хватает схемы.
    const result = checkMicAvailability(scope({ isSecureContext: false }));

    expect(result.available).toBe(false);
    expect(result.reason).toContain('HTTPS');
  });

  test('нехватка HTTPS важнее отсутствия mediaDevices', () => {
    // На http mediaDevices не определён именно из-за схемы — сообщать надо
    // про причину, а не про следствие.
    const result = checkMicAvailability(
      scope({ isSecureContext: false, navigator: { mediaDevices: undefined as never } }),
    );

    expect(result.reason).toContain('HTTPS');
  });

  test('старый браузер без AudioWorklet — отдельное сообщение', () => {
    const result = checkMicAvailability(scope({ AudioWorkletNode: undefined }));

    expect(result.available).toBe(false);
    expect(result.reason).not.toContain('HTTPS');
  });
});

describe('randomUuid', () => {
  const withoutRandomUuid = {
    getRandomValues: (array: Uint8Array) => {
      for (let i = 0; i < array.length; i += 1) array[i] = (i * 37) % 256;
      return array;
    },
  } as Crypto;

  test('использует crypto.randomUUID, когда он есть', () => {
    const native = { randomUUID: () => 'из-нативного' } as unknown as Crypto;

    expect(randomUuid(native)).toBe('из-нативного');
  });

  test('без crypto.randomUUID отдаёт настоящий UUID v4', () => {
    // capture_id уходит на сервер, где контракт объявляет его как UUID:
    // произвольная строка не прошла бы валидацию.
    const value = randomUuid(withoutRandomUuid);

    expect(value).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  });

  test('не бросает, когда crypto.randomUUID отсутствует', () => {
    // Ровно этот TypeError и делал кнопку записи молча мёртвой.
    expect(() => randomUuid(withoutRandomUuid)).not.toThrow();
  });
});
