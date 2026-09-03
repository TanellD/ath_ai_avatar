#!/usr/bin/env node
import * as PARAMS from "../modules/parameters.mjs";
import { Processor } from "../modules/processor.mjs";
import { Training } from "../modules/training.mjs";
import * as utils from './training-node-utils.mjs';
import * as fs from 'node:fs';

// Default options
let input = ".";
let output = null;
let override = false;
let help = false;

// Help message
const helpText = utils.buildHelpMessage(
  'node compile.mjs [options] -o <model>',
  [
    { flag: '-h, --help', description: 'Show this help message.' },
    { flag: '-i, --input <dir|pattern>', description: 'Directory or file pattern for input files (.wav), default "' + input + '".' },
    { flag: '-o, --output <file>', description: 'HeadLipSync binary model file (.bin).' },
    { flag: '--override <file>', description: 'Replace the output file if it exists.' },
  ],
  "Compiles speech (.wav) and visemes+timestamps (.json) into Gaussian binary model (.bin)."
);

// Parse command-line arguments
const args = process.argv.slice(2);
args.forEach((arg, index) => {
  const next = args[index + 1];
  if ( (arg === '--input' || arg === '-i') && next ) {
    input = next;
  } else if ( (arg === '--output' || arg === '-o')  && next ) {
    output = next;
  } else if (arg === '--override' ) {
    override = true;
  } else if (arg === '--help' || arg === '-h' ) {
    help = true;
  }
});
if ( !output || help ) {
  console.log(helpText);
  process.exit(1);
}

// Check if output file already exists
const outputFileExists = await utils.fileExists(output);
if ( outputFileExists && !override ) {
  console.log(`Output file already exists. Use --override option to override.`);
  process.exit(1);
}

const wavFiles = await utils.findFiles(input, [".wav"]);
const N = wavFiles.length;
if (N === 0) {
  console.log('No audio files found.');
  process.exit(1);
}

console.log('Audio files found:');
console.log(wavFiles);

// Check JSON files
const jsonFiles = [];
for(let i=0; i<N; i++) {
  const parts = wavFiles[i].split(".");
  parts[parts.length-1] = "json";
  const jsonFile = parts.join(".");
  const jsonFileExists = await utils.fileExists(jsonFile);
  if ( !jsonFileExists ) {
    console.log(`❌ Exiting, JSON file ${jsonFile} does not exists.`);
    exit(1);
  }
  jsonFiles.push(jsonFile);
}

console.log();

// Load first file to get sample rate and run warm-up
const warmup = await utils.getFloat32ArrayFromWav(wavFiles[0]);

// Init HeadLipSyncProcessor
const processor = new Processor({
  sampleRate: warmup.sampleRate, // Source sample rate
  samplesN: 512,
  samplesHop: 32,
  processorOptions: {
    featureEventsEnabled: true // We need mean feature vectors
  },
  parameterData: {
    vadMode: 0
  }
});

// Warm-up with the first file
const S0 = warmup.samples.length;
console.log(`Warm-up`);
for( let j=0; j<S0; j+=128 ) {
  const block = new Float32Array(warmup.samples.buffer, j * 4, Math.min(128, S0-j) );
  processor.process(block);
}

// Prototypes
const prototypes = {};

// Process WAV/JSON files
for(let i=0; i<N; i++) {
  const wavFile = wavFiles[i];
  const jsonFile = jsonFiles[i];
  console.log(`Processing ${i+1}/${N}: ${wavFile}`);

  // Load files
  const { samples } = await utils.getFloat32ArrayFromWav(wavFile);
  const data = await utils.getDataFromJson(jsonFile);

  // Calculate start/end
  data.forEach ( x => {
    x.start = x.t - 5;
    x.end = x.t + x.d / 2;
  });

  // Process viseme messages
  const V = data.length;
  let ndx = 0;
  processor.worklet.port.postMessage = (o) => {
    if ( o.event === "feature" ) {
      if ( o.le < -5 ) return; // Skip low-energy samples
      const t = 1000 * o.t; // Convert to milliseconds
      while ( ndx < V && t > data[ndx].end ) ndx++;
      if ( ndx < V ) {
        const d = data[ndx];
        if ( t >= d.start ) {
          const phoneme = d.phoneme;
          if ( prototypes.hasOwnProperty(phoneme) ) {
            prototypes[phoneme].vs.push(o.vector.slice());
          } else {
            prototypes[phoneme] = { phoneme, viseme: d.viseme, vs: [o.vector.slice()] };
          }
        }
      }
    }
  }
  
  // Flag timer reset
  processor.update({ timerReset: true });

  // Process
  const S = samples.length;
  for( let j=0; j<S; j+=128 ) {
    const block = new Float32Array(samples.buffer, j * 4, Math.min(128, S-j) );
    processor.process(block);
  }
  
}

// Generate silence
prototypes["s1"] = { phoneme: "s1", viseme: 14, vs: [] };
for( let i=0; i<5000; i++ ) {
  const silence1 = new Float32Array(PARAMS.MFCC_COEFF_N_WITH_DELTAS);
  for( let j=0; j<PARAMS.MFCC_COEFF_N_WITH_DELTAS; j++ ) {
    const rnd = (Math.random() - 0.5) / 10;
    silence1[j] = rnd;
  }
  prototypes["s1"].vs.push(silence1);
}

// Print status
let s = "\nStatistics: [";
Object.values(prototypes).forEach( (x,i) => {
  if ( i>0 ) s += ","; 
  s += " " + x.phoneme + ": " + x.vs.length;
});
s += " ]";
console.log(s);

// Write the model
console.log(`\nCalculating Gaussian prototypes:`);
try {
  const training = new Training();
  const outStream = fs.createWriteStream(output);
  for( let p of Object.values(prototypes) ) {
    
    if ( p.vs.length < 100 ) {
      console.log(`Skipping ${p.phoneme}/${p.viseme} with N=${p.vs.length}.`);
      continue;
    }
    
    const m = training.computePrototype(p.phoneme, 0, p.viseme, p.vs);

    //Statistics
    console.log(`\nPrototype ${p.phoneme} [${utils.visemes[p.viseme]}]:`);
    let s = "mu:      [";
    m.mu.forEach( (x,i) => {
      if ( i > 0 ) s += ", ";
      s += x.toFixed(2);
    });
    s += "]";
    s += "\nsigmaInv: [";
    m.sigmaInv.forEach( (y,i) => {
      s += '\n[ '
      y.forEach( (x,j) => {
        if ( j > 0 ) s += ", ";
        s += x.toFixed(2);
      })
      s += "]";
    });
    s += "\n]";
    s += "\nBin:      [";
    const floats = new Float32Array(m.bin);
    floats.forEach( x => s += " " + x.toFixed(2) );
    s += "]";
    console.log(s);

    const buf = Buffer.from(m.bin);
    if (!outStream.write(buf)) {
      await new Promise(resolve => outStream.once('drain', resolve));
    }
  }

  await new Promise(resolve => outStream.end(resolve));
  console.log(`✅ OK! Binary model written to "${output}"`);

} catch(err) {
    console.error(`❌ Error: `, err.message);
}

