/**
 * Рендер персонажа — TalkingHead + HeadAudio (Claude.md §10).
 *
 * Заменяет прежнюю заглушку (SimliAvatar.tsx). Выбор провалидирован веткой
 * `poc`: бесплатный, self-hosted, MIT-лицензированный стек, без managed-API
 * стоимости за минуту — реально работает end-to-end на русском тексте. Это
 * осознанное отклонение от рекомендации Simli в Claude.md §10, где Simli уже
 * помечен предупреждением «репозиторий переведён в read-only, статус SDK
 * проверить перед подключением».
 *
 * HeadAudio делает то, что старый LipSync.ts пытался эмулировать поллингом
 * `requestAnimationFrame`, но честнее: анализирует РЕАЛЬНО проигрываемый звук
 * через AudioWorklet (в аудио-потоке, посэмпльно) и толкает значения визем
 * прямо в морф-таргеты меша. Это строже требования §3 «часы — воспроизводимое
 * аудио», чем опрос по кадрам — здесь вообще нет отдельного опроса, только
 * реакция на реальные проходящие сэмплы. `requestAnimationFrame` внутри
 * TalkingHead — это каденция рендера WebGL-сцены, а не источник времени для
 * визем; величины визем в каждый кадр уже посчитаны воркletом заранее.
 *
 * Известное ограничение, унаследованное от `poc` и не устранённое здесь:
 * `model-en-mixed.bin` — модель, обученная на английской фонетике. VAD
 * относительно языко-агностичен, точность визем на русской речи не
 * проверялась. Протокол проверки для этого случая описан в Claude.md,
 * Приложение Б, но применён не был.
 */

import { useEffect, useRef } from 'react';
import { stabilizeNonHumanoidPose, guardAvatarResize } from './runtimeGuards';
import {
  AnimationMixer,
  LoopOnce,
  type AnimationClip,
  type Object3D,
  type Quaternion,
  type Vector3,
} from 'three';

// Обычный import, а не URL: этот файл в src/, а не в public/. Vite не даёт
// импортировать файлы из public/ как ES-модуль в dev-режиме («This file is
// in /public and will be copied as-is...») — только через fetch/addModule.
// Ворклет-часть того же рантайма (headworklet.mjs и его зависимости) как раз
// грузится так и поэтому осталась в public/ — см. README рядом с обоими.
import { HeadAudio } from '@/vendor/headaudio/headaudio.mjs';
import type { AvatarId, Emotion } from '@/contracts/events';

const HEADAUDIO_WORKLET_URL = '/vendor/headaudio/headworklet.mjs';
const HEADAUDIO_MODEL_URL = '/vendor/headaudio/model-en-mixed.bin';

export type CameraView = 'head' | 'upper' | 'mid' | 'full';

/** Поправка камеры под пропорции конкретной модели — своя на каждый план. */
export interface CameraTuning {
  cameraDistance: number;
  cameraY: number;
}

export interface AvatarModelConfig {
  id: AvatarId;
  label: string;
  url: string;
  humanoidPose: boolean;
  cameraView: CameraView;
  /**
   * setView() считает план от avatarHeight, но размеры кадра зашиты
   * константами под человеческую голову. Модель с другими пропорциями
   * промахивается в каждом плане по-своему, поэтому поправка — не одна
   * пара чисел, а таблица.
   */
  cameraTuning: Record<CameraView, CameraTuning>;
  embeddedIdleAnimations?: boolean;
}

export const AVATAR_MODELS = {
  aith: {
    id: 'avatar-aith',
    label: 'avatar-aith (основная)',
    url: '/assets/avatar/avatar-aith.glb',
    humanoidPose: true,
    cameraView: 'head',
    // Человекоподобная модель — планы TalkingHead рассчитаны ровно на неё,
    // поправка не нужна.
    cameraTuning: {
      head: { cameraDistance: 0, cameraY: 0 },
      upper: { cameraDistance: 0, cameraY: 0 },
      mid: { cameraDistance: 0, cameraY: 0 },
      full: { cameraDistance: 0, cameraY: 0 },
    },
  },
  tom: {
    id: 'tom-avatar',
    label: 'Tom (тестовая)',
    url: '/assets/avatar/tom_avatar.glb',
    humanoidPose: false,
    cameraView: 'head',
    // Голова Тома 0.616 против ~0.23 у человека при почти том же уровне глаз
    // (1.448 против 1.482): avatarHeight выходит нормальным, а кадр — нет.
    // Числа посчитаны из формулы setView() под фактическую геометрию GLB:
    // центр головы y = 1.392, глубина z = 0.215, рост 1.70.
    cameraTuning: {
      head: { cameraDistance: 2.62, cameraY: 0.82 },
      upper: { cameraDistance: 1.14, cameraY: 0.59 },
      mid: { cameraDistance: -0.36, cameraY: 0.18 },
      full: { cameraDistance: -0.35, cameraY: 0.15 },
    },
    // Второй AnimationMixer конфликтует с системой поз TalkingHead: оба пишут
    // в одни кости, и побеждает тот, кто записал последним. Пока выключено —
    // Том стоит в собственной rest-позе. Возвращать idle-движение следует
    // через штатный head.mixer, а не отдельным микшером.
    embeddedIdleAnimations: false,
  },
} as const satisfies Record<string, AvatarModelConfig>;

/** Что аватар отдаёт наверх, когда готов принимать звук. */
export interface AvatarPlaybackHandle {
  audioCtx: AudioContext;
  /** Куда подключать AudioBufferSourceNode проигрываемых реплик. */
  destination: AudioNode;
  /** Вернуть лицо в нейтральное положение — вызывается из cancelPlayback(). */
  resetFace: () => void;
  /** Применить эмоцию реплики к мимике TalkingHead. */
  setEmotion: (emotion: Emotion) => void;
  /** Сменить крупность плана с поправкой под пропорции текущей модели. */
  setView: (view: CameraView) => void;
}

/**
 * Звук без лица — запасной путь, когда аватар не поднялся.
 *
 * Claude.md §8 формулирует направление деградации прямо: «лицо замирает, голос
 * продолжается. Не наоборот». До этой функции было ровно наоборот: любая ошибка
 * WebGL или загрузки GLB оставляла `audio === null`, и экран становился тупиком
 * — кнопка старта навсегда висела «Загружаем персонажа…», композер и микрофон
 * были заблокированы, тренировка не начиналась вовсе.
 *
 * На телефоне это не гипотеза: 12.7 МБ модели по сотовой сети и агрессивная
 * потеря WebGL-контекста при сворачивании вкладки. Сессия обязана идти и без
 * лица: персонаж слышен, субтитры идут, оценка выставляется.
 *
 * Мимика становится пустышками — вызывать их можно откуда угодно, они ничего
 * не знают о том, что лица нет.
 */
export function createFacelessPlayback(): AvatarPlaybackHandle {
  const audioCtx = new AudioContext();
  return {
    audioCtx,
    destination: audioCtx.destination,
    resetFace: () => {},
    setEmotion: () => {},
    setView: () => {},
  };
}

/**
 * Базовое удаление камеры по планам — из setView() самой TalkingHead
 * (`z += 2` для head, 4.5 для upper и т.д.). Нужно здесь, потому что
 * `cameraDistance` в опциях — это СЛАГАЕМОЕ к этой базе, а не итоговое
 * расстояние: чтобы отодвинуть камеру на N процентов, надо знать, от чего
 * считать проценты.
 */
const VIEW_BASE_DISTANCE: Record<CameraView, number> = {
  head: 2,
  upper: 4.5,
  mid: 8,
  full: 12,
};

/**
 * Телефон ли это — по грубому указателю и узкому экрану, а не по user-agent:
 * строку агента подделывают и переписывают, а способ ввода и ширина описывают
 * ровно то, что нам нужно.
 */
export function isHandheld(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(pointer: coarse) and (max-width: 820px)').matches;
}

/**
 * Настройки рендера под устройство.
 *
 * `modelFPS: 60` при вендорном дефолте 30 и сырой `devicePixelRatio` (2–3.5 на
 * телефоне, то есть 4–12× работы на фрагментах) — это прямой нагрев и расход
 * батареи, а не качество картинки: лицо в панели размером с ладонь от 60 кадров
 * и тройного пиксельного отношения лучше не становится.
 */
export interface RenderProfile {
  modelFPS: number;
  /**
   * Коэффициент, а не итоговое разрешение: вендор умножает `modelPixelRatio`
   * на `window.devicePixelRatio` сам (`setPixelRatio(opt * dpr)`), поэтому
   * чтобы ограничить эффективное отношение двойкой, сюда идёт 2/dpr.
   */
  pixelRatio: number;
}

export function renderProfile(
  handheld = isHandheld(),
  devicePixelRatio = typeof window === 'undefined' ? 1 : window.devicePixelRatio || 1,
): RenderProfile {
  if (!handheld) return { modelFPS: 60, pixelRatio: 1 };
  return { modelFPS: 30, pixelRatio: Math.min(2, devicePixelRatio) / devicePixelRatio };
}

/** Итоговая поправка расстояния под требуемый зум. */
function tunedDistance(model: AvatarModelConfig, view: CameraView, zoomOut: number): number {
  const base = VIEW_BASE_DISTANCE[view];
  return (model.cameraTuning[view].cameraDistance + base) * zoomOut - base;
}

interface Props {
  /** Профиль модели фиксируется на время жизни компонента. */
  model?: AvatarModelConfig;
  /** Во время речи держать зрительный контакт с пользователем, а не с курсором. */
  isSpeaking: boolean;
  /**
   * Множитель удаления камеры: 1 — кадр как задуман профилем модели,
   * 1.4 — на 40% дальше. Нужен лаборатории, где модель разглядывают
   * целиком, а не ведут с ней разговор.
   */
  zoomOut?: number;
  onReady: (handle: AvatarPlaybackHandle) => void;
  onError: (message: string) => void;
  /**
   * Доля загрузки модели, 0..1. Основная модель весит 12.7 МБ, и по сотовой
   * сети это десятки секунд, в течение которых кнопка старта просто написана
   * «Загружаем персонажа…» и ничем не отличается от зависшей.
   */
  onProgress?: (fraction: number) => void;
}

export function TalkingHeadAvatar({
  onProgress,
  model = AVATAR_MODELS.aith,
  isSpeaking,
  zoomOut = 1,
  onReady,
  onError,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const startedRef = useRef(false);
  const cursorGazeRef = useRef<CursorGazeController | null>(null);
  const avatarCleanupRef = useRef<(() => void) | null>(null);
  const isSpeakingRef = useRef(isSpeaking);

  useEffect(() => {
    isSpeakingRef.current = isSpeaking;
    cursorGazeRef.current?.setEnabled(!isSpeaking);
  }, [isSpeaking]);

  useEffect(() => {
    const container = containerRef.current;
    // startedRef переживает двойной вызов эффекта в StrictMode (dev) —
    // React монтирует эффект, чистит, монтирует снова на ТОМ ЖЕ инстансе
    // компонента, не трогая DOM-узел между вызовами. Значит достаточно
    // гарантировать, что setup() запустится не больше одного раза за всё
    // время жизни компонента, — что этот флаг и делает.
    //
    // Раньше здесь ещё был флаг `cancelled`, выставляемый в cleanup и
    // прерывавший setup() на середине. Это ломало ровно тот сценарий, ради
    // которого писался: первый (фиктивный, StrictMode-шный) cleanup
    // выставлял cancelled=true ДО того, как setup() успевал дойти до
    // showAvatar() — единственный реальный вызов setup() тихо обрывался на
    // середине, без ошибки (это и есть смысл cancelled-проверки), аватар не
    // появлялся, GLB не запрашивался, onReady не вызывался — и композер
    // оставался заблокирован навсегда. startedRef один справляется с задачей
    // «выполнить ровно один раз», без риска убить единственную попытку.
    if (!container) return;
    if (startedRef.current) {
      return () => {
        cursorGazeRef.current?.detach();
        avatarCleanupRef.current?.();
        avatarCleanupRef.current = null;
      };
    }
    startedRef.current = true;

    // Отдельная не-nullable привязка: container сам по себе типизирован как
    // HTMLDivElement | null, и TS не переносит сужение внутрь вложенной
    // async-функции, замыкающейся на него.
    const mount: HTMLDivElement = container;

    async function setup() {
      try {
        const { TalkingHead } = await import('@met4citizen/talkinghead');
        let embeddedIdle: EmbeddedIdleController | null = null;
        let restoreRootPosition: (() => void) | undefined;

        const initialTuning = model.cameraTuning[model.cameraView];

        const profile = renderProfile();
        const head = new TalkingHead(mount, {
          ttsEndpoint: 'N/A',
          lipsyncModules: [],
          cameraView: model.cameraView,
          cameraDistance: tunedDistance(model, model.cameraView, zoomOut),
          cameraY: initialTuning.cameraY,
          mixerGainSpeech: 3,
          // На телефоне ниже: см. renderProfile(). modelPixelRatio у вендора
          // умножается на window.devicePixelRatio, поэтому здесь коэффициент,
          // а не итоговое значение.
          modelFPS: profile.modelFPS,
          modelPixelRatio: profile.pixelRatio,
          cameraRotateEnable: false,
        });

        const disposeResize = guardAvatarResize(head, mount);
        avatarCleanupRef.current = disposeResize;

        await head.audioCtx.audioWorklet.addModule(HEADAUDIO_WORKLET_URL);

        const headaudio = new HeadAudio(head.audioCtx, {
          processorOptions: {
            vadEventsEnabled: true,
            visemeEventsEnabled: true,
          },
          parameterData: {
            vadMode: 1,
          },
        });

        await headaudio.loadModel(HEADAUDIO_MODEL_URL);

        head.audioSpeechGainNode.connect(headaudio);

        // Небольшая задержка перед реверб-узлом — унаследована от poc без
        // задокументированного обоснования сверх «так лучше совпадает по
        // фазе»; значение не пересчитывалось.
        const delayNode = new DelayNode(head.audioCtx, { delayTime: 0.15 });
        head.audioSpeechGainNode.disconnect(head.audioReverbNode);
        head.audioSpeechGainNode.connect(delayNode);
        delayNode.connect(head.audioReverbNode);

        headaudio.onvalue = (key: string, value: number) => {
          if (head.mtAvatar && head.mtAvatar[key]) {
            Object.assign(head.mtAvatar[key], { newvalue: value, needsUpdate: true });
          }
        };

        if (!model.humanoidPose) prepareNonHumanoidPose(head);

        head.opt.update = (dt: number) => {
          headaudio.update(dt);
          embeddedIdle?.update(dt);
          restoreRootPosition?.();
        };

        headaudio.onstarted = () => {
          head.lookAtCamera(500);
          if (model.humanoidPose) head.speakWithHands();
        };

        await head.showAvatar(
          {
            url: model.url,
            body: 'F',
            avatarMood: 'neutral',
          },
          // Вендор зовёт onprogress событиями XHR; total известен не всегда
          // (нет Content-Length при chunked), тогда доли просто не будет.
          (event: ProgressEvent) => {
            if (event.lengthComputable && event.total > 0) {
              onProgress?.(event.loaded / event.total);
            }
          },
        );

        if (!model.humanoidPose) {
          restoreRootPosition = stabilizeNonHumanoidPose(head);
          if (model.embeddedIdleAnimations) {
            embeddedIdle = playEmbeddedIdleAnimations(head);
            avatarCleanupRef.current = () => {
              disposeResize();
              embeddedIdle?.dispose();
            };
          }
        }

        const cursorGaze = attachCursorGaze(head, mount);
        cursorGazeRef.current = cursorGaze;
        cursorGaze.setEnabled(!isSpeakingRef.current);

        const applyView = (view: CameraView) => {
          head.setView(view, {
            cameraDistance: tunedDistance(model, view, zoomOut),
            cameraY: model.cameraTuning[view].cameraY,
          });
        };

        // Мобильный Safari отбирает WebGL-контекст у фоновых вкладок, и
        // вернуть его сам TalkingHead не умеет. Без этого обработчика лицо
        // просто чернеет молча; с ним ошибка доходит наверх, и сессия
        // переключается на звук без лица (§8) вместо тихой поломки.
        const canvas = mount.querySelector('canvas');
        canvas?.addEventListener('webglcontextlost', (event) => {
          event.preventDefault();
          onError('WebGL-контекст потерян');
        });

        onReady({
          audioCtx: head.audioCtx,
          destination: head.audioSpeechGainNode,
          resetFace: () => headaudio.resetAll(),
          setEmotion: (emotion) => applyEmotion(head, emotion),
          setView: applyView,
        });
      } catch (error) {
        onError(error instanceof Error ? error.message : 'Не удалось загрузить аватара');
      }
    }

    void setup();

    // TalkingHead не даёт полного dispose(), но глобальные обработчики взгляда
    // снять можем и обязаны: иначе после навигации они продолжат держать head.
    return () => {
      cursorGazeRef.current?.detach();
      avatarCleanupRef.current?.();
      avatarCleanupRef.current = null;
    };
    // zoomOut читается один раз при инициализации сцены: startedRef держит
    // setup() однократным, и менять зум на лету компонент не обещает.
  }, [model, zoomOut, onReady, onError, onProgress]);

  return <div ref={containerRef} className="avatar" />;
}

type TimedPoseTransform = (Vector3 | Quaternion) & { t?: number; d?: number };

interface NonHumanoidRuntime {
  animClock: number;
  animations: AnimationClip[];
  animQueue: Array<{ template?: { name?: string }; ts: number[] }>;
  armature: Object3D;
  scene: Object3D;
  poseAvatar: { props: Record<string, TimedPoseTransform> };
  poseBase: { props: Record<string, TimedPoseTransform> };
  poseTarget: { props: Record<string, TimedPoseTransform> };
  poseDelta: { props: Record<string, { x: number; y: number; z: number }> };
  updatePoseDelta: () => void;
}

interface EmbeddedIdleController {
  update(dt: number): void;
  dispose(): void;
}

function asNonHumanoidRuntime(head: unknown): NonHumanoidRuntime {
  return head as NonHumanoidRuntime;
}

/**
 * В npm-сборке TalkingHead 1.7.0 нет callback `onpreprocess`, поэтому очищаем
 * человеческую базовую позу до showAvatar(). Его штатная ветка `else` сама
 * снимет исходные трансформации костей Tom до первого кадра.
 */
function prepareNonHumanoidPose(head: unknown): void {
  asNonHumanoidRuntime(head).poseBase.props = {};
}

/** Последовательно проигрывать только авторские idle-клипы из GLB Tom. */
function playEmbeddedIdleAnimations(head: unknown): EmbeddedIdleController {
  const runtime = asNonHumanoidRuntime(head);
  const clips = runtime.animations.filter((clip) => clip.name.toLowerCase().includes('idle'));
  if (clips.length === 0) {
    return { update: () => undefined, dispose: () => undefined };
  }

  let animationRoot = runtime.armature;
  while (animationRoot.parent && animationRoot.parent !== runtime.scene) {
    animationRoot = animationRoot.parent;
  }

  const mixer = new AnimationMixer(animationRoot);
  const nativeHipsPosition = runtime.poseBase.props['Hips.position']?.clone();
  let clipIndex = 0;

  const playNext = () => {
    mixer.stopAllAction();
    const clip = clips[clipIndex % clips.length];
    clipIndex += 1;
    mixer.clipAction(clip).reset().setLoop(LoopOnce, 1).fadeIn(0.15).play();
  };

  mixer.addEventListener('finished', playNext);
  playNext();

  return {
    update: (dt: number) => {
      if (nativeHipsPosition) {
        runtime.poseAvatar.props['Hips.position']?.copy(nativeHipsPosition);
      }
      mixer.update(dt / 1000);
    },
    dispose: () => {
      mixer.removeEventListener('finished', playNext);
      mixer.stopAllAction();
    },
  };
}

interface EmotionHead {
  setMood(mood: string): void;
  setFixedValue(morphTarget: string, value: number | null): void;
}

const EMOTION_OVERLAYS = [
  'browDownLeft',
  'browDownRight',
  'browInnerUp',
  'browOuterUpLeft',
  'browOuterUpRight',
  'eyeSquintLeft',
  'eyeSquintRight',
  'eyeWideLeft',
  'eyeWideRight',
  'mouthFrownLeft',
  'mouthFrownRight',
] as const;

function applyEmotion(head: EmotionHead, emotion: Emotion): void {
  for (const target of EMOTION_OVERLAYS) head.setFixedValue(target, null);

  if (emotion === 'friendly') {
    head.setMood('happy');
    return;
  }
  if (emotion === 'angry') {
    head.setMood('angry');
    return;
  }
  if (emotion === 'sad') {
    head.setMood('sad');
    return;
  }
  if (emotion === 'irritated') {
    head.setMood('neutral');
    head.setFixedValue('browDownLeft', 0.3);
    head.setFixedValue('browDownRight', 0.3);
    head.setFixedValue('eyeSquintLeft', 0.12);
    head.setFixedValue('eyeSquintRight', 0.12);
    head.setFixedValue('mouthFrownLeft', 0.14);
    head.setFixedValue('mouthFrownRight', 0.14);
    return;
  }
  if (emotion === 'excited') {
    head.setMood('happy');
    head.setFixedValue('eyeWideLeft', 0.22);
    head.setFixedValue('eyeWideRight', 0.22);
    head.setFixedValue('browOuterUpLeft', 0.18);
    head.setFixedValue('browOuterUpRight', 0.18);
    return;
  }
  if (emotion === 'surprised') {
    head.setMood('neutral');
    head.setFixedValue('eyeWideLeft', 0.5);
    head.setFixedValue('eyeWideRight', 0.5);
    head.setFixedValue('browInnerUp', 0.5);
    head.setFixedValue('browOuterUpLeft', 0.35);
    head.setFixedValue('browOuterUpRight', 0.35);
    return;
  }

  head.setMood('neutral');
}

interface CursorGazeHead {
  setFixedValue(morphTarget: string, value: number | null): void;
  lookAtCamera(durationMs: number): void;
}

interface CursorGazeController {
  setEnabled(enabled: boolean): void;
  detach(): void;
}

/**
 * Быстрое слежение за курсором, перенесённое из рабочего PoC.
 *
 * Глаза реагируют первыми, голова догоняет чуть медленнее. Горизонтальная
 * координата считается от центра области аватара, а не всего окна: справа
 * находится панель диалога, поэтому симметричная шкала окна давала заметно
 * более слабый поворот вправо.
 */
function attachCursorGaze(head: CursorGazeHead, mount: HTMLElement): CursorGazeController {
  const gaze = {
    eyeX: 0,
    eyeY: 0,
    targetEyeX: 0,
    targetEyeY: 0,
    headX: 0,
    headY: 0,
    targetHeadX: 0,
    targetHeadY: 0,
    active: false,
    enabled: true,
    lastPointer: null as { x: number; y: number } | null,
    animationFrame: null as number | null,
  };

  const animate = () => {
    gaze.eyeX += (gaze.targetEyeX - gaze.eyeX) * 0.8;
    gaze.eyeY += (gaze.targetEyeY - gaze.eyeY) * 0.8;
    gaze.headX += (gaze.targetHeadX - gaze.headX) * 0.5;
    gaze.headY += (gaze.targetHeadY - gaze.headY) * 0.5;

    head.setFixedValue('eyesRotateY', gaze.eyeX);
    head.setFixedValue('eyesRotateX', gaze.eyeY);
    head.setFixedValue('headRotateY', gaze.headX);
    head.setFixedValue('headRotateX', gaze.headY);

    const moving =
      Math.abs(gaze.targetEyeX - gaze.eyeX) > 0.005 ||
      Math.abs(gaze.targetEyeY - gaze.eyeY) > 0.005 ||
      Math.abs(gaze.targetHeadX - gaze.headX) > 0.005 ||
      Math.abs(gaze.targetHeadY - gaze.headY) > 0.005;

    if (moving) {
      gaze.animationFrame = requestAnimationFrame(animate);
      return;
    }

    gaze.animationFrame = null;
    if (!gaze.active) releaseGaze();
  };

  const requestFrame = () => {
    if (gaze.animationFrame === null) gaze.animationFrame = requestAnimationFrame(animate);
  };

  const normalizeHorizontal = (clientX: number) => {
    const rect = mount.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const distance = clientX >= centerX ? window.innerWidth - centerX : centerX;
    return Math.max(-1, Math.min(1, (clientX - centerX) / Math.max(distance, 1)));
  };

  const updateTargets = (clientX: number, clientY: number) => {
    const normalizedX = normalizeHorizontal(clientX);
    const normalizedY = clientY / window.innerHeight * 2 - 1;
    const verticalHeadRange = normalizedY < 0 ? 0.34 : 0.18;

    gaze.targetEyeX = Math.max(-0.85, Math.min(0.85, normalizedX * 0.85));
    gaze.targetEyeY = Math.max(-0.55, Math.min(0.55, normalizedY * 0.55));
    gaze.targetHeadX = Math.max(-0.28, Math.min(0.28, normalizedX * 0.28));
    gaze.targetHeadY = Math.max(-0.34, Math.min(0.18, normalizedY * verticalHeadRange));
    gaze.active = true;
    requestFrame();
  };

  const onPointerMove = (event: PointerEvent) => {
    if (event.pointerType === 'touch') return;
    gaze.lastPointer = { x: event.clientX, y: event.clientY };
    if (gaze.enabled) updateTargets(event.clientX, event.clientY);
  };

  const onMouseLeave = () => {
    gaze.lastPointer = null;
    if (!gaze.enabled) return;
    gaze.targetEyeX = 0;
    gaze.targetEyeY = 0;
    gaze.targetHeadX = 0;
    gaze.targetHeadY = 0;
    gaze.active = false;
    requestFrame();
  };

  function releaseGaze() {
    head.setFixedValue('eyesRotateY', null);
    head.setFixedValue('eyesRotateX', null);
    head.setFixedValue('headRotateY', null);
    head.setFixedValue('headRotateX', null);
    head.lookAtCamera(250);
  }

  function focusOnCamera() {
    // У avatar-aith штатная точка lookAtCamera визуально получается ниже
    // объектива. Отрицательный X поднимает взгляд и немного подбородок,
    // сохраняя естественную позу во время разговора.
    head.lookAtCamera(200);
    head.setFixedValue('eyesRotateY', 0);
    head.setFixedValue('eyesRotateX', -0.16);
    head.setFixedValue('headRotateY', 0);
    head.setFixedValue('headRotateX', -0.04);
  }

  window.addEventListener('pointermove', onPointerMove, { passive: true });
  document.documentElement.addEventListener('mouseleave', onMouseLeave);

  const setEnabled = (enabled: boolean) => {
    if (gaze.enabled === enabled) return;
    gaze.enabled = enabled;

    if (enabled) {
      if (gaze.lastPointer) updateTargets(gaze.lastPointer.x, gaze.lastPointer.y);
      return;
    }

    gaze.active = false;
    gaze.eyeX = gaze.eyeY = gaze.headX = gaze.headY = 0;
    gaze.targetEyeX = gaze.targetEyeY = gaze.targetHeadX = gaze.targetHeadY = 0;
    if (gaze.animationFrame !== null) cancelAnimationFrame(gaze.animationFrame);
    gaze.animationFrame = null;
    focusOnCamera();
  };

  return {
    setEnabled,
    detach: () => {
      window.removeEventListener('pointermove', onPointerMove);
      document.documentElement.removeEventListener('mouseleave', onMouseLeave);
      if (gaze.animationFrame !== null) cancelAnimationFrame(gaze.animationFrame);
      releaseGaze();
    },
  };
}
