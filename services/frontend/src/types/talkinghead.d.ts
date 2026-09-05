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

declare module 'three' {
  export const LoopOnce: number;

  export interface Object3D {
    parent: Object3D | null;
  }

  export interface AnimationClip {
    name: string;
  }

  export interface AnimationAction {
    reset(): AnimationAction;
    setLoop(mode: number, repetitions: number): AnimationAction;
    fadeIn(duration: number): AnimationAction;
    play(): AnimationAction;
  }

  export class AnimationMixer {
    constructor(root: Object3D);
    clipAction(clip: AnimationClip): AnimationAction;
    update(deltaTime: number): void;
    stopAllAction(): AnimationMixer;
    addEventListener(type: 'finished', listener: () => void): void;
    removeEventListener(type: 'finished', listener: () => void): void;
  }

  export interface Vector3 {
    x: number;
    y: number;
    z: number;
    clone(): Vector3;
    copy(value: Vector3 | Quaternion): Vector3;
  }

  export interface Quaternion {
    x: number;
    y: number;
    z: number;
    w: number;
    clone(): Quaternion;
    copy(value: Vector3 | Quaternion): Quaternion;
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
    setView(view: string, options?: { cameraDistance?: number; cameraY?: number }): void;
    lookAtCamera(durationMs: number): void;
    setMood(mood: string): void;
    setFixedValue(morphTarget: string, value: number | null, durationMs?: number): void;
    speakWithHands(): void;
  }
}
