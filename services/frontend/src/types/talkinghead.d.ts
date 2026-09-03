/**
 * Минимальные объявления типов для аватар-стека — ни один из двух пакетов не
 * поставляет собственный .d.ts, оба написаны на чистом JS.
 *
 * `allowJs` в tsconfig выключен намеренно (не хотим, чтобы TS пытался
 * типизировать сторонний JS целиком), поэтому оба специфаера — и
 * `@met4citizen/talkinghead` (реальный npm-пакет), и
 * `@/vendor/headaudio/headaudio.mjs` (собранный рантайм HeadAudio,
 * скопированный в src/vendor/headaudio/, а не установленный) — резолвятся
 * через ambient-декларации, а не через попытку прочитать типы из самого
 * JS-файла.
 *
 * Объявлено только то, что реально используется в TalkingHeadAvatar.tsx — без
 * претензии на полноту API обоих пакетов.
 */

declare module '@/vendor/headaudio/headaudio.mjs' {
  export class HeadAudio extends AudioWorkletNode {
    constructor(
      audioCtx: AudioContext,
      options?: {
        processorOptions?: Record<string, unknown>;
        parameterData?: Record<string, unknown>;
      },
    );
    loadModel(url: string, reset?: boolean): Promise<void>;
    update(dt: number): void;
    start(): void;
    stop(): void;
    resetAll(): void;
    onvalue: ((key: string, value: number) => void) | null;
    onstarted: (() => void) | null;
  }
}

declare module '@met4citizen/talkinghead' {
  export interface TalkingHeadOptions {
    ttsEndpoint?: string;
    lipsyncModules?: string[];
    cameraView?: string;
    mixerGainSpeech?: number;
    modelFPS?: number;
    cameraRotateEnable?: boolean;
    [key: string]: unknown;
  }

  export interface ShowAvatarOptions {
    url: string;
    body?: string;
    avatarMood?: string;
    [key: string]: unknown;
  }

  export interface MorphTarget {
    newvalue: number;
    needsUpdate: boolean;
  }

  export class TalkingHead {
    constructor(container: HTMLElement, options?: TalkingHeadOptions);
    audioCtx: AudioContext;
    audioSpeechGainNode: GainNode;
    audioReverbNode: AudioNode;
    mtAvatar: Record<string, MorphTarget>;
    opt: { update?: (dt: number) => void; [key: string]: unknown };
    showAvatar(options: ShowAvatarOptions): Promise<void>;
    lookAtCamera(durationMs: number): void;
    speakWithHands(): void;
  }
}
