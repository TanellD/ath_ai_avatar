import assert from 'node:assert/strict';

let Processor;
const messages = [];

globalThis.sampleRate = 48_000;
globalThis.AudioWorkletProcessor = class {
  constructor() {
    this.port = {
      onmessage: null,
      postMessage(message) {
        messages.push(message);
      },
    };
  }
};
globalThis.registerProcessor = (_name, implementation) => {
  Processor = implementation;
};

await import('../public/pcm-capture.worklet.js');

const processor = new Processor();
let remaining = 48_000;
while (remaining > 0) {
  const length = Math.min(128, remaining);
  processor.process([[new Float32Array(length).fill(0.25)]]);
  remaining -= length;
}
processor.port.onmessage({ data: { type: 'flush' } });

const frames = messages.filter((message) => message.type === 'pcm');
const samples = frames.reduce((sum, message) => sum + message.buffer.byteLength / 2, 0);

assert.ok(samples >= 15_999 && samples <= 16_000, `unexpected sample count: ${samples}`);
assert.ok(frames.every((message) => message.buffer.byteLength <= 640));
assert.equal(messages.at(-1).type, 'flushed');

console.log(`PCM worklet: 48000 -> ${samples} samples, ${frames.length} frames`);
