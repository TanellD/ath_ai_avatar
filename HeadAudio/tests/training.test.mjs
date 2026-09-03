
import { describe, test, expect } from '@jest/globals';
import * as PARAMS from "../modules/parameters.mjs";
import { Training } from '../modules/training.mjs';


describe('Performance', () => {

  // Training instance
  const training = new Training();

  // Training vectors
  const M = 50;
  const N = 1000;
  const vss = Array.from({length: M}, (_,i) => {
    return Array.from({ length: N}, () => {
      return Array.from({ length: PARAMS.MFCC_COEFF_N_WITH_DELTAS }, (_,j) => {
        return Math.random() * 2 - 1;
      });
    });
  });

  test('computing prototypes', () => {
    
    const start = process.hrtime.bigint();
    for( let i=0; i<M; i++ ) {
      const p = training.computePrototype( "p", i % 15, i, vss[i]);
    }
    const end = process.hrtime.bigint();
    const durationMs = Number(end - start) / 1_000_000 / M;
    console.log(`Prototype computing took ${durationMs.toFixed(3)} ms per one prototype of ${N} samples.`);

  });

});
