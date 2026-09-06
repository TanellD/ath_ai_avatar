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

/**
 * Свет TalkingHead по умолчанию: заливка intensity 2 и направленный
 * 0x8888aa — серо-синий. Синева вымывает тёплые тона кожи, а сильная
 * равномерная заливка съедает контраст. Модели с запечёнными в текстуру
 * цветами страдают от этого заметнее, чем модели с собственными
 * PBR-картами, поэтому поправка задаётся на модель, а не глобально:
 * менять свет остальным аватарам ради одного нельзя.
 */
export interface AvatarLighting {
  lightAmbientIntensity: number;
  lightDirectColor: number;
  lightDirectIntensity: number;
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
  /** Поправка света; без неё берутся умолчания библиотеки. */
  lighting?: AvatarLighting;
  /**
   * Длительность полного хода виземы 0->1, мс. В HeadAudio зашито 100, но в
   * речи виземы сменяются каждые 60-120 мс — рот не успевает доехать до формы
   * и щёлкает между ними. Чем крупнее рот модели, тем заметнее. Без значения
   * остаётся ванильное поведение.
   */
  visemeRampMs?: number;
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
  vincent: {
    id: 'vincent-avatar',
    label: 'Vincent',
    url: '/assets/avatar/vincent.glb',
    // ВРЕМЕННО false. Шаблоны поз TalkingHead написаны под T-позу: у
    // avatar-aith руки в rest смотрят строго горизонтально [1,0,0], и
    // шаблон доворачивает их вниз примерно на 90° ('LeftShoulder.rotation'
    // ≈ 1.6/-1.77 рад). Vincent смоделирован в A-позе, руки уже опущены на
    // 34.7° — тот же доворот уводит их на столько же дальше, внутрь
    // корпуса. Отсюда и вывернутые руки, и посторонняя геометрия,
    // заплывающая в тело.
    //
    // Лечится приведением rest-позы Vincent к T-позе (развернуть кости рук,
    // применить позу как rest, перезапечь тело) — до тех пор позы тела
    // отключены. Лицо, виземы, моргание и взгляд работают в любом случае:
    // ими TalkingHead управляет независимо от этого флага.
    humanoidPose: false,
    cameraView: 'head',
    // Риг TalkingHead-совместимый: отдельные кости глаз и полный набор
    // лицевых morph targets. Тело человеческих пропорций, поэтому планы
    // upper/mid/full кадрируются штатно и поправки не требуют.
    //
    // План head — требует. Голова Vincent 0.487 (от подбородка 1.239 до
    // макушки волос 1.726) против 0.267 у avatar-aith, то есть в 1.83 раза
    // крупнее при почти том же уровне глаз (1.542 против 1.482). Формула
    // setView() берёт размер кадра от avatarHeight, а он у обоих почти
    // одинаковый — кадр выходит один и тот же, а голова в него не влезает:
    // при нулях кадр 1.393..1.743 обрезает подбородок, заполнение 1.39.
    //
    // Числа подобраны так, чтобы голова занимала в кадре ту же долю, что и
    // у avatar-aith (0.76): z = 2 + 1.65 = 3.65 даёт кадр 1.154..1.793 —
    // запас 0.085 под подбородком и 0.067 над волосами.
    cameraTuning: {
      head: { cameraDistance: 1.65, cameraY: 0.75 },
      upper: { cameraDistance: 0, cameraY: 0 },
      mid: { cameraDistance: 0, cameraY: 0 },
      full: { cameraDistance: 0, cameraY: 0 },
    },
    // Цвет Vincent запечён в текстуры (материалы Blender строились на
    // MIX_SHADER, который glTF не переносит), поэтому вся тональность
    // приходит от света. С умолчаниями библиотеки он выходит блёклым:
    // синий ключ гасит кожу, заливка 2 убирает контраст.
    // Ключ переведён в тёплый белый и усилен, заливка убавлена.
    // Рот у Vincent крупный и мультяшный: на ванильных 100 мс артикуляция
    // читается дёрганой. 190 мс дают внятное движение без суеты.
    visemeRampMs: 190,
    lighting: {
      lightAmbientIntensity: 0.85,
      lightDirectColor: 0xfff0e2,
      lightDirectIntensity: 46,
    },
  },
} as const satisfies Record<string, AvatarModelConfig>;

export const AVATAR_MODEL_LIST: AvatarModelConfig[] = [
  AVATAR_MODELS.aith,
  AVATAR_MODELS.tom,
  AVATAR_MODELS.vincent,
];

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

interface Props {
  /** Профиль модели фиксируется на время жизни компонента. */
  model?: AvatarModelConfig;
  /** Во время речи держать зрительный контакт с пользователем, а не с курсором. */
  isSpeaking: boolean;
  onReady: (handle: AvatarPlaybackHandle) => void;
  onError: (message: string) => void;
}

export function TalkingHeadAvatar({
  model = AVATAR_MODELS.aith,
  isSpeaking,
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

        const initialTuning = model.cameraTuning[model.cameraView];

        const head = new TalkingHead(mount, {
          ttsEndpoint: 'N/A',
          lipsyncModules: [],
          cameraView: model.cameraView,
          cameraDistance: initialTuning.cameraDistance,
          cameraY: initialTuning.cameraY,
          mixerGainSpeech: 3,
          modelFPS: 60,
          cameraRotateEnable: false,
          ...(model.lighting ?? {}),
        });

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

        if (model.visemeRampMs) {
          (headaudio as unknown as { visemeRampMs: number }).visemeRampMs = model.visemeRampMs;
        }

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
        };

        headaudio.onstarted = () => {
          head.lookAtCamera(500);
          if (model.humanoidPose) head.speakWithHands();
        };

        await head.showAvatar({
          url: model.url,
          body: 'F',
          avatarMood: 'neutral',
        });

        if (!model.humanoidPose) {
          stabilizeNonHumanoidPose(head);
          if (model.embeddedIdleAnimations) {
            embeddedIdle = playEmbeddedIdleAnimations(head);
            avatarCleanupRef.current = () => embeddedIdle?.dispose();
          }
        }

        const cursorGaze = attachCursorGaze(head, mount);
        cursorGazeRef.current = cursorGaze;
        cursorGaze.setEnabled(!isSpeakingRef.current);

        // TalkingHead.onResize() не защищён от нулевого размера контейнера:
        // при сворачивании окна clientWidth/clientHeight дают 0, camera.aspect
        // становится NaN, и OrbitControls остаются в испорченном состоянии —
        // после разворачивания аватар оказывается вне кадра. Возвращаем камеру
        // на место, как только контейнер снова получает ненулевой размер.
        let currentView: CameraView = model.cameraView;
        const applyView = (view: CameraView) => {
          currentView = view;
          const tuning = model.cameraTuning[view];
          head.setView(view, {
            cameraDistance: tuning.cameraDistance,
            cameraY: tuning.cameraY,
          });
        };

        let hadSize = mount.clientWidth > 0 && mount.clientHeight > 0;
        const sizeGuard = new ResizeObserver(() => {
          const hasSize = mount.clientWidth > 0 && mount.clientHeight > 0;
          if (hasSize && !hadSize) applyView(currentView);
          hadSize = hasSize;
        });
        sizeGuard.observe(mount);

        const disposeIdle = avatarCleanupRef.current;
        avatarCleanupRef.current = () => {
          sizeGuard.disconnect();
          disposeIdle?.();
        };

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
  }, [model, onReady, onError]);

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
  setPoseFromTemplate: (template: unknown, ms?: number) => void;
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

/** Зафиксировать нативную базу Tom и оставить из pose-delta только поворот головы. */
function stabilizeNonHumanoidPose(head: unknown): void {
  const runtime = asNonHumanoidRuntime(head);

  for (const [key, original] of Object.entries(runtime.poseBase.props)) {
    const base = original.clone() as TimedPoseTransform;
    const target = original.clone() as TimedPoseTransform;
    target.t = runtime.animClock;
    target.d = 0;
    runtime.poseBase.props[key] = base;
    runtime.poseTarget.props[key] = target;
    runtime.poseAvatar.props[key]?.copy(original);
  }

  const proceduralPose = runtime.animQueue.find((item) => item.template?.name === 'pose');
  if (proceduralPose) proceduralPose.ts[0] = Infinity;

  // Обезвредить очередь мало: TalkingHead ставит новые анимации позы по ходу
  // работы. В цикле анимации есть ветка case 'pose', которая выбирает
  // очередной шаблон и применяет его через setPoseFromTemplate; строка выше
  // гасит только тот элемент очереди, что существовал на момент загрузки.
  //
  // Симптом на не-человекоподобной модели: спустя время персонаж «подрастает»
  // и дёргается вбок. Шаблоны задают абсолютные величины —
  // 'Hips.position' y = 1 при собственном тазе Vincent на 0.8806 даёт +12 см
  // роста, а 'Hips.rotation' и повороты бёдер до 3 рад уводят фигуру вбок.
  // Ярче всего проявляется после сворачивания вкладки: пока она скрыта,
  // requestAnimationFrame не идёт, и на возврате накопившееся срабатывает разом.
  //
  // Поэтому глушим сам метод: модель остаётся в собственной rest-позе.
  runtime.setPoseFromTemplate = () => {};

  const updatePoseDelta = runtime.updatePoseDelta.bind(runtime);
  runtime.updatePoseDelta = () => {
    for (const [key, delta] of Object.entries(runtime.poseDelta.props)) {
      if (key === 'Head.quaternion') continue;
      delta.x = 0;
      delta.y = 0;
      delta.z = 0;
    }
    updatePoseDelta();
  };
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
    // У avatar-aith штатная точка lookAtCamera визуально получается чуть ниже
    // объектива. Небольшой отрицательный X поднимает взгляд и совсем немного
    // подбородок, сохраняя естественную позу во время разговора.
    head.lookAtCamera(200);
    head.setFixedValue('eyesRotateY', 0);
    head.setFixedValue('eyesRotateX', -0.1);
    head.setFixedValue('headRotateY', 0);
    head.setFixedValue('headRotateX', -0.025);
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
