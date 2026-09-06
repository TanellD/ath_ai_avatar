import { describe, expect, it } from 'vitest';

import { PauseDetector } from './PauseDetector';

function frame(amplitude: number, samples = 50): ArrayBuffer {
  const pcm = new Int16Array(samples);
  pcm.fill(Math.round(amplitude * 32_767));
  return pcm.buffer;
}

function detector() {
  return new PauseDetector({
    sampleRate: 1_000,
    speechConfirmationMs: 100,
    endpointSilenceMs: 300,
    minimumSpeechRms: 0.1,
    noiseMultiplier: 3,
    initialNoiseRms: 0.01,
  });
}

describe('PauseDetector', () => {
  it('не завершает запись, если речи ещё не было', () => {
    const value = detector();
    for (let index = 0; index < 20; index += 1) {
      expect(value.push(frame(0.01))).toBe(false);
    }
  });

  it('завершает запись один раз после подтверждённой речи и длинной паузы', () => {
    const value = detector();
    value.push(frame(0.3));
    value.push(frame(0.3));
    for (let index = 0; index < 5; index += 1) {
      expect(value.push(frame(0.01))).toBe(false);
    }
    expect(value.push(frame(0.01))).toBe(true);
    expect(value.push(frame(0.01))).toBe(false);
  });

  it('не считает короткую паузу концом реплики', () => {
    const value = detector();
    value.push(frame(0.3));
    value.push(frame(0.3));
    for (let index = 0; index < 4; index += 1) value.push(frame(0.01));
    expect(value.push(frame(0.3))).toBe(false);
    for (let index = 0; index < 5; index += 1) value.push(frame(0.01));
    expect(value.push(frame(0.01))).toBe(true);
  });

  it('reset начинает распознавание новой реплики', () => {
    const value = detector();
    value.push(frame(0.3));
    value.push(frame(0.3));
    for (let index = 0; index < 6; index += 1) value.push(frame(0.01));
    value.reset();
    expect(value.push(frame(0.01))).toBe(false);
  });
});
