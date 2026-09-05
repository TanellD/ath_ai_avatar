export interface PauseDetectorConfig {
  sampleRate: number;
  speechConfirmationMs: number;
  endpointSilenceMs: number;
  minimumSpeechRms: number;
  noiseMultiplier: number;
  initialNoiseRms: number;
}

export const DEFAULT_PAUSE_DETECTOR_CONFIG: PauseDetectorConfig = {
  sampleRate: 16_000,
  // Консервативные стартовые параметры для PTT. Их надо уточнять по записям
  // реальных пользователей, прежде чем использовать в hands-free режиме.
  speechConfirmationMs: 160,
  endpointSilenceMs: 6_000,
  minimumSpeechRms: 0.012,
  noiseMultiplier: 3,
  initialNoiseRms: 0.004,
};

/**
 * Локальный energy-VAD только для автозавершения уже начатой PTT-записи.
 * Время считается по PCM-сэмплам, поэтому фоновые таймеры вкладки не влияют
 * на границу реплики. До подтверждённой речи одна лишь тишина endpoint не даёт.
 */
export class PauseDetector {
  private readonly config: PauseDetectorConfig;
  private noiseRms: number;
  private speechSamples = 0;
  private silenceSamples = 0;
  private speechDetected = false;
  private endpointEmitted = false;

  constructor(config: Partial<PauseDetectorConfig> = {}) {
    this.config = { ...DEFAULT_PAUSE_DETECTOR_CONFIG, ...config };
    this.noiseRms = this.config.initialNoiseRms;
  }

  reset(): void {
    this.noiseRms = this.config.initialNoiseRms;
    this.speechSamples = 0;
    this.silenceSamples = 0;
    this.speechDetected = false;
    this.endpointEmitted = false;
  }

  push(frame: ArrayBuffer): boolean {
    if (this.endpointEmitted) return false;
    const samples = new Int16Array(frame);
    if (!samples.length) return false;

    const rms = frameRms(samples);
    const speechThreshold = Math.max(
      this.config.minimumSpeechRms,
      this.noiseRms * this.config.noiseMultiplier,
    );

    if (!this.speechDetected) {
      if (rms >= speechThreshold) {
        this.speechSamples += samples.length;
        if (this.speechSamples >= this.samplesFor(this.config.speechConfirmationMs)) {
          this.speechDetected = true;
        }
      } else {
        this.speechSamples = 0;
        // Подстраиваемся только до начала речи, чтобы голос пользователя не
        // поднял noise floor и не стал считаться фоном.
        this.noiseRms = this.noiseRms * 0.95 + rms * 0.05;
      }
      return false;
    }

    // Гистерезис не даёт тихим окончаниям слов выглядеть как пауза.
    const releaseThreshold = Math.max(
      this.config.minimumSpeechRms * 0.65,
      speechThreshold * 0.8,
    );
    if (rms >= releaseThreshold) {
      this.silenceSamples = 0;
      return false;
    }

    this.silenceSamples += samples.length;
    if (this.silenceSamples < this.samplesFor(this.config.endpointSilenceMs)) return false;
    this.endpointEmitted = true;
    return true;
  }

  private samplesFor(milliseconds: number): number {
    return Math.ceil((this.config.sampleRate * milliseconds) / 1_000);
  }
}

function frameRms(samples: Int16Array): number {
  let squares = 0;
  for (const sample of samples) {
    const normalized = sample / 32_768;
    squares += normalized * normalized;
  }
  return Math.sqrt(squares / samples.length);
}
