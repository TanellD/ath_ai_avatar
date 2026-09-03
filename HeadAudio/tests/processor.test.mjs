
import { describe, test, expect } from '@jest/globals';
import * as PARAMS from '../modules/parameters.mjs';
import { Processor } from '../modules/processor.mjs';
import { Training } from '../modules/training.mjs';
import * as utils from '../training/training-node-utils.mjs';
import * as fs from 'node:fs';


// Load WAV file
const { sampleRate, samples } = await utils.getFloat32ArrayFromWav("./tests/test44100Hz.wav");

// Processor instance
const processor = new Processor({ sampleRate });
const training = new Training();

// Load binary model
const bin = await fs.promises.readFile('./dist/model-en-mixed.bin');
const buffer = bin.buffer.slice( bin.byteOffset, bin.byteOffset + bin.byteLength );

// Extract records
const model = [];
const len = buffer.byteLength;
let pos = 0;
while( (pos + PARAMS.RECORD_OFFSET) <= len ) {
  const record = new Float32Array(buffer, pos, PARAMS.RECORD_LEN);
  const p = training.decodeBinaryRecord(record);
  model.push(p);
  pos += PARAMS.RECORD_OFFSET;
}

// Import model to processor
processor._onmessage({ data: { event: "model", reset: true, model } });


describe('Performance', () => {

  // Warm-up
  const W = 10*128;
  for( let j=0; j<W; j+=128 ) {
    const block = new Float32Array(samples.buffer, j * 4, Math.min(128, W-j) );
    processor.process(block);
  }
  
  test('process audio', () => {

    // Process
    const durations = [];
    const S = samples.length;
    for( let j=0; j<S; j+=128 ) {
      const start = process.hrtime.bigint();
      const block = new Float32Array(samples.buffer, j * 4, Math.min(128, S-j) );
      processor.process(block);
      const end = process.hrtime.bigint();
      const durationMs = Number(end - start) / 1_000_000;
      durations.push(durationMs);
    }

    // Write to CSV file
    const csvContent = durations.map( r => r.toFixed(5)).join("\n");
    fs.writeFileSync("./tests/processor.csv", csvContent);
    console.log("CSV file written!");

    // Ignore downsampling frames (<0.02) to calculate processor median
    const typical = durations.filter( x => x >= 0.02 );
    const median = typical.sort((a, b) => a - b)[Math.floor(typical.length / 2)];
    console.log(`Model prediction took ${median.toFixed(3)} ms per frame (median).`);

    expect(median).toBeLessThan(0.1);
  });

});
