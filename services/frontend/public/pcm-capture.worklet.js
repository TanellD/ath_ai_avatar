class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetRate = 16000;
    this.ratio = sampleRate / this.targetRate;
    this.source = [];
    this.position = 0;
    this.output = [];
    this.frameSamples = 320;
    this.port.onmessage = (event) => {
      if (event.data?.type === 'flush') {
        this.emit(true);
        this.port.postMessage({ type: 'flushed' });
      }
    };
  }

  process(inputs) {
    const channels = inputs[0];
    if (!channels?.length) return true;
    for (let index = 0; index < channels[0].length; index += 1) {
      let mono = 0;
      for (const channel of channels) mono += channel[index] ?? 0;
      this.source.push(mono / channels.length);
    }
    while (this.position + 1 < this.source.length) {
      const left = Math.floor(this.position);
      const fraction = this.position - left;
      const sample = this.source[left] * (1 - fraction) + this.source[left + 1] * fraction;
      this.output.push(Math.max(-1, Math.min(1, sample)));
      this.position += this.ratio;
      if (this.output.length >= this.frameSamples) this.emit(false);
    }
    // Keep the final source sample between render quanta: interpolation for
    // the next output sample may need it together with the next block.
    const consumed = Math.min(
      Math.floor(this.position),
      Math.max(0, this.source.length - 1),
    );
    if (consumed > 0) {
      this.source = this.source.slice(consumed);
      this.position -= consumed;
    }
    return true;
  }

  emit(includeRemainder) {
    while (this.output.length >= this.frameSamples || (includeRemainder && this.output.length)) {
      const count = Math.min(this.frameSamples, this.output.length);
      const pcm = new Int16Array(count);
      for (let index = 0; index < count; index += 1) {
        const sample = this.output[index];
        pcm[index] = sample < 0 ? Math.round(sample * 32768) : Math.round(sample * 32767);
      }
      this.output.splice(0, count);
      this.port.postMessage({ type: 'pcm', buffer: pcm.buffer }, [pcm.buffer]);
    }
  }
}

registerProcessor('pcm-capture-processor', PcmCaptureProcessor);
