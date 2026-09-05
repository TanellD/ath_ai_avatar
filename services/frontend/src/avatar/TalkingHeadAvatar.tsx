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

// Обычный import, а не URL: этот файл в src/, а не в public/. Vite не даёт
// импортировать файлы из public/ как ES-модуль в dev-режиме («This file is
// in /public and will be copied as-is...») — только через fetch/addModule.
// Ворклет-часть того же рантайма (headworklet.mjs и его зависимости) как раз
// грузится так и поэтому осталась в public/ — см. README рядом с обоими.
import { HeadAudio } from '@/vendor/headaudio/headaudio.mjs';
import type { Emotion } from '@/contracts/events';

/** Запасная модель, если реестр аватаров недоступен. */
const FALLBACK_AVATAR_URL = '/assets/avatar/avatar-aith.glb';
const HEADAUDIO_WORKLET_URL = '/vendor/headaudio/headworklet.mjs';
const HEADAUDIO_MODEL_URL = '/vendor/headaudio/model-en-mixed.bin';

/** Что аватар отдаёт наверх, когда готов принимать звук. */
export interface AvatarPlaybackHandle {
  audioCtx: AudioContext;
  /** Куда подключать AudioBufferSourceNode проигрываемых реплик. */
  destination: AudioNode;
  /** Вернуть лицо в нейтральное положение — вызывается из cancelPlayback(). */
  resetFace: () => void;
  /** Применить эмоцию реплики к мимике TalkingHead. */
  setEmotion: (emotion: Emotion) => void;
}

interface Props {
  /** Во время речи держать зрительный контакт с пользователем, а не с курсором. */
  isSpeaking: boolean;
  onReady: (handle: AvatarPlaybackHandle) => void;
  /** Модель текущего аватара; берётся из реестра scenario-service. */
  modelUrl?: string;
  /** Тип рига TalkingHead для этой модели. */
  body?: 'F' | 'M';
  onError: (message: string) => void;
}

export function TalkingHeadAvatar({ isSpeaking, onReady, onError, modelUrl, body = 'F' }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const startedRef = useRef(false);
  const cursorGazeRef = useRef<CursorGazeController | null>(null);
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
    if (startedRef.current) return () => cursorGazeRef.current?.detach();
    startedRef.current = true;

    // Отдельная не-nullable привязка: container сам по себе типизирован как
    // HTMLDivElement | null, и TS не переносит сужение внутрь вложенной
    // async-функции, замыкающейся на него.
    const mount: HTMLDivElement = container;

    async function setup() {
      try {
        const { TalkingHead } = await import('@met4citizen/talkinghead');

        const head = new TalkingHead(mount, {
          ttsEndpoint: 'N/A',
          lipsyncModules: [],
          cameraView: 'head',
          mixerGainSpeech: 3,
          modelFPS: 60,
          cameraRotateEnable: false,
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

        head.opt.update = headaudio.update.bind(headaudio);

        headaudio.onstarted = () => {
          head.lookAtCamera(500);
          head.speakWithHands();
        };

        await head.showAvatar({
          url: modelUrl ?? FALLBACK_AVATAR_URL,
          body,
          avatarMood: 'neutral',
        });

        const cursorGaze = attachCursorGaze(head, mount);
        cursorGazeRef.current = cursorGaze;
        cursorGaze.setEnabled(!isSpeakingRef.current);

        onReady({
          audioCtx: head.audioCtx,
          destination: head.audioSpeechGainNode,
          resetFace: () => headaudio.resetAll(),
          setEmotion: (emotion) => applyEmotion(head, emotion),
        });
      } catch (error) {
        onError(error instanceof Error ? error.message : 'Не удалось загрузить аватара');
      }
    }

    void setup();

    // TalkingHead не даёт полного dispose(), но глобальные обработчики взгляда
    // снять можем и обязаны: иначе после навигации они продолжат держать head.
    return () => cursorGazeRef.current?.detach();
  }, [onReady, onError, modelUrl, body]);

  return <div ref={containerRef} className="avatar" />;
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
