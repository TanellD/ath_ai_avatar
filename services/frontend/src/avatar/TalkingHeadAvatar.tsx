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

const AVATAR_URL = '/assets/avatar/avatar-aith.glb';
const HEADAUDIO_WORKLET_URL = '/vendor/headaudio/headworklet.mjs';
const HEADAUDIO_MODEL_URL = '/vendor/headaudio/model-en-mixed.bin';

/** Что аватар отдаёт наверх, когда готов принимать звук. */
export interface AvatarPlaybackHandle {
  audioCtx: AudioContext;
  /** Куда подключать AudioBufferSourceNode проигрываемых реплик. */
  destination: AudioNode;
  /** Вернуть лицо в нейтральное положение — вызывается из cancelPlayback(). */
  resetFace: () => void;
}

interface Props {
  onReady: (handle: AvatarPlaybackHandle) => void;
  onError: (message: string) => void;
}

export function TalkingHeadAvatar({ onReady, onError }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const startedRef = useRef(false);

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
    if (!container || startedRef.current) return;
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
          url: AVATAR_URL,
          body: 'F',
          avatarMood: 'neutral',
        });

        onReady({
          audioCtx: head.audioCtx,
          destination: head.audioSpeechGainNode,
          resetFace: () => headaudio.resetAll(),
        });
      } catch (error) {
        onError(error instanceof Error ? error.message : 'Не удалось загрузить аватара');
      }
    }

    void setup();

    // Без cleanup-функции: startedRef уже не даст запустить setup() снова, а
    // TalkingHead не даёт полного dispose() — при реальном размонтировании
    // (уход со страницы) WebGL-контекст и AudioContext просто освободит
    // сборщик мусора вместе с containerRef, когда на них ничего больше не
    // будет ссылаться. onReady/onError, вызванные уже после размонтирования
    // компонента, в React 18 безопасны — сеттер состояния на размонтированном
    // компоненте молча ничего не делает.
  }, [onReady, onError]);

  return <div ref={containerRef} className="avatar" />;
}
