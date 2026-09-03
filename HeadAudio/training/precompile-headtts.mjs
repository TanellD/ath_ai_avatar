#!/usr/bin/env node
import * as fs from 'fs';
import { Buffer } from 'buffer';
import * as utils from './training-node-utils.mjs';

// Default options
let input = ".";
let rest = "http://127.0.0.1:8882/v1/synthesize";
let voice = "af_bella";
let override = false;
let help = false;

// Help message
const helpText = utils.buildHelpMessage(
  'node precompile-headtts.mjs [options]',
  [
    { flag: '-h, --help', description: 'Show this help message.' },
    { flag: '-i, --input <dir|pattern>', description: 'Directory or file pattern for input text files (.txt), default "' + input + '".' },
    { flag: '-r, --rest <url>', description: 'HeadTTS REST API URL, default "' + rest + '".' },
    { flag: '-v, --voice <voice>', description: 'HeadTTS voice, default "' + voice + '".' },
    { flag: '--override', description: 'Replace files if they exist.' },
  ],
  "Generates speech (.wav) and visemes+timestamps (.json) from text files (.txt) using " +
  "HeadTTS REST API. HeadTTS REST server must be running. Output files are stored in the input directory."
);

// Parse command-line arguments
const args = process.argv.slice(2);
args.forEach((arg, index) => {
  const next = args[index + 1];
  if ( (arg === '--input' || arg === '-i') && next) {
    input = next;
  } else if ( (arg === '--rest' || arg === '-r') && next ) {
    rest = next;
  } else if ( (arg === '--voice' || arg === '-v') && next ) {
    voice = next;
  } else if ( arg === '--override' ) {
    override = true;
  } else if ( arg === '--help' || arg === '-h' ) {
    help = true;
  }
});
if ( help ) {
  console.log(helpText);
  process.exit(1);
}

// Constants
const SAMPLE_RATE = 24000;
const CHANNELS = 1;
const BITS_PER_SAMPLE = 16;

async function tts(txtFile, wavFile, jsonFile, restUrl, voice) {
  let totalSentences = 0;
  let totalSamples = 0;
  const pcmChunks = [];
  const json = [];

  for await (const s of utils.readSentencesStream(txtFile)) {
    process.stdout.write(`\rSentence #: ${++totalSentences}`);

    const section = { section: s, ps: [] };

    // TTS
    try {
      const response = await fetch(restUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          input: s,
          voice: voice,
          language: "en-us",
          speed: 1,
          audioEncoding: "pcm"
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP error, status: ${response.status}`);
      }
      const data = await response.json();

      // Write PCM samples
      const base64 = data.audio;
      const pcmBuffer = Buffer.from(base64, 'base64');
      pcmChunks.push(pcmBuffer);

      // Add visemes
      const durationMs = (totalSamples / SAMPLE_RATE) * 1000;
      const N = data.visemes.length;
      for( let i=0; i<N; i++ ) {
        const phoneme = data.phonemes?.[i];
        const viseme = utils.visemeIds[data.visemes[i]];
        const vtime = durationMs + data.vtimes[i];
        const vduration = data.vdurations[i];
        section.ps.push( { p: phoneme, v: viseme, t: vtime, d: vduration });
      }

      // Add counter
      const samplesInChunk = pcmBuffer.length / (BITS_PER_SAMPLE / 8);
      totalSamples += samplesInChunk;

      // Add section
      json.push(section);
      
    } catch (err) {
      console.error('\n❌ Error:', err);
    }
    
  }

  process.stdout.write(`\n`);

  // Save to WAV file
  if ( pcmChunks.length ) {
    const pcmData = Buffer.concat(pcmChunks);
    const header = utils.makeWavHeader(pcmData.length, SAMPLE_RATE, CHANNELS, BITS_PER_SAMPLE);
    const wavBuffer = Buffer.concat([header, pcmData]);
    await fs.promises.writeFile(wavFile, wavBuffer);
    console.log(`✅ Saved ${wavFile} with ${totalSamples} samples total.`);
  }

  // Save to JSON file
  if ( json.length ) {  
    const s = JSON.stringify(json)
      .replace(/^\[/g,"[\n  ")
      .replaceAll("]},","]},\n  ")
      .replace(/]$/g,"\n]");

    // Write JSON file
    await fs.promises.writeFile(jsonFile, s);
    console.log(`✅ OK! Saved ${jsonFile} with visemes and timestamps.`);
  }

}

const txtFiles = await utils.findFiles(input, [".txt"]);
if (txtFiles.length === 0) {
  console.log('No text files found.');
  process.exit(1);
}

console.log('Text files found:');
console.log(txtFiles);

// WAV files
const wavFiles = txtFiles.map( x => {
  const parts = x.split(".");
  parts[parts.length-1] = "wav";
  return parts.join(".");
});

// JSON files
const jsonFiles = txtFiles.map( x => {
  const parts = x.split(".");
  parts[parts.length-1] = "json";
  return parts.join(".");
});

const N = txtFiles.length;
for(let i=0; i<N; i++) {
  const txtFile = txtFiles[i];
  const wavFile = wavFiles[i];
  const jsonFile = jsonFiles[i];
  console.log(`\nProcessing ${i+1}/${N}: ${txtFile}`);

  // Check if both output files already exist
  if ( !override ) {
    const wavFileExists = await utils.fileExists(wavFile);
    const jsonFileExists = await utils.fileExists(jsonFile);
    if ( wavFileExists && jsonFileExists ) {
      console.log(`❌ Skipping, both WAV and JSON files already exists.`);
      continue;
    }
  }

  // Run TTS
  await tts(txtFile, wavFile, jsonFile, rest, voice);
  
}

