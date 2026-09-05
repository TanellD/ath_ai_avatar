/**
 * Экран сотрудника — Claude.md §8.
 *
 * Здесь сходятся все инварианты клиента, поэтому читать этот файл стоит вместе
 * с §6:
 *
 *   - поколение (`genRef`) — источник истины для фильтрации событий;
 *   - отправка реплики вызывает cancelPlayback() ДО отправки в сокет;
 *   - аудио-чанки идут только через AudioQueue, который сам отбрасывает чужие;
 *   - субтитры, панель истории и индикатор состояния читают время у
 *     PlaybackClock / реальное завершение воспроизведения у AudioQueue,
 *     и больше нигде.
 *
 * `AudioContext` теперь создаёт и владеет им TalkingHeadAvatar (это его
 * `head.audioCtx`), а не этот компонент: PlaybackClock и AudioQueue
 * собираются только после того, как аватар отдаст готовый контекст через
 * onReady — до этого момента отправка реплики недоступна (см. MessageComposer
 * disabled), так же как в проверенном PoC send оставался disabled, пока
 * аватар не загрузился.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';

import { gatewayApi } from '@/api/client';
import { AudioQueue } from '@/audio/AudioQueue';
import { PlaybackClock } from '@/audio/PlaybackClock';
import { cancelPlayback } from '@/audio/cancelPlayback';
import {
  AVATAR_MODEL_LIST,
  AVATAR_MODELS,
  TalkingHeadAvatar,
  type AvatarModelConfig,
  type AvatarPlaybackHandle,
} from '@/avatar/TalkingHeadAvatar';
import { ChatPanel, type ChatTurn } from '@/components/ChatPanel';
import { MessageComposer } from '@/components/MessageComposer';
import { PlaybackIndicator, type PlaybackState } from '@/components/PlaybackIndicator';
import { PushToTalkToggle } from '@/components/PushToTalkToggle';
import { SessionEndOverlay } from '@/components/SessionEndOverlay';
import { SessionStartOverlay } from '@/components/SessionStartOverlay';
import type { ServerEvent, SubtitleEvent } from '@/contracts/events';
import { Subtitles } from '@/subtitles/Subtitles';
import type { SessionError } from '@/types/errors';
import { useSessionSocket } from '@/ws/useSessionSocket';

interface AudioRig {
  audioCtx: AudioContext;
  clock: PlaybackClock;
  queue: AudioQueue;
  resetFace: () => void;
  setEmotion: AvatarPlaybackHandle['setEmotion'];
}

export function TraineeSession() {
  const { scenarioId = '' } = useParams();

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [error, setError] = useState<SessionError | null>(null);
  const [transcript, setTranscript] = useState<ChatTurn[]>([]);
  const [cues, setCues] = useState<SubtitleEvent[]>([]);
  const [subtitlesFrozen, setSubtitlesFrozen] = useState(false);
  const [pushToTalk, setPushToTalk] = useState(false);
  const [playback, setPlayback] = useState<PlaybackState>('disconnected');
  const [audio, setAudio] = useState<AudioRig | null>(null);
  /**
   * Пока false — сокет не открыт, и персонаж молчит. Разделение нужно из-за
   * автоплея: агент говорит первым (§1), а звук в браузере не пойдёт, пока
   * пользователь не совершит жест. См. SessionStartOverlay.
   */
  const [started, setStarted] = useState(false);
  /** Тренировка окончена — по кнопке сотрудника или по решению автомата (§3). */
  const [finished, setFinished] = useState(false);
  const [avatarModel, setAvatarModel] = useState<AvatarModelConfig>(AVATAR_MODELS.aith);

  /**
   * Текущее поколение. Именно ref, а не useState: значение читается в
   * обработчике сокета синхронно, и устаревшее замыкание здесь означало бы
   * пропущенный отброс чанка — то есть нарушение метрики 4.
   */
  const genRef = useRef(0);
  const emotionGenerationRef = useRef<number | null>(null);

  const handleAvatarReady = useCallback((handle: AvatarPlaybackHandle) => {
    const clock = new PlaybackClock(handle.audioCtx);
    // Четвёртый параметр — onIdle: единственный правильный источник для
    // индикатора «персонаж говорит». `action` от сервера приходит, когда
    // байты уже ОТПРАВЛЕНЫ, а не когда они доиграли — раньше индикатор либо
    // не гас вовсе (обычный переход stay/next_stage не трогал playback), либо
    // гас слишком рано. Теперь состояние идёт от факта тишины в колонках.
    const queue = new AudioQueue(handle.audioCtx, clock, handle.destination, () =>
      setPlayback('idle'),
    );
    // Оба поля обязательны: audioCtx нужен, чтобы разблокировать автоплей по
    // клику «Начать» (агент говорит первым), setEmotion — чтобы лицо
    // отыгрывало эмоцию реплики.
    setAudio({
      audioCtx: handle.audioCtx,
      clock,
      queue,
      resetFace: handle.resetFace,
      setEmotion: handle.setEmotion,
    });
  }, []);

  const handleAvatarError = useCallback((message: string) => {
    setError({ type: 'audio', message: 'Не удалось загрузить аватара', details: message });
  }, []);

  // Сессия заводится по нажатию «Начать», а не на монтировании страницы —
  // см. handleStart. Раньше строка в БД появлялась на каждый заход, и список
  // тренировок у методиста состоял в основном из пустышек.

  // AudioContext больше не наш: им владеет TalkingHeadAvatar (head.audioCtx),
  // закрывать его здесь при размонтировании было бы вмешательством в чужой
  // жизненный цикл. См. докстринг TalkingHeadAvatar.tsx про best-effort cleanup.

  // -------------------------------------------------------------- события WS

  const handleEvent = useCallback(
    (event: ServerEvent) => {
      switch (event.type) {
        case 'token':
          setPlayback('speaking');
          setTranscript((lines) => appendAgentToken(lines, event.text));
          break;

        case 'audio_chunk':
          // Аватар мог ещё не догрузиться (13 МБ GLB) к моменту первого
          // чанка — тогда его попросту некуда проигрывать. Очередь также сама
          // сверит gen_id ещё раз — намеренное дублирование проверки: чанк
          // мог быть декодирован уже после перебивания.
          if (audio) {
            if (emotionGenerationRef.current !== event.gen_id) {
              audio.setEmotion(event.emotion);
              emotionGenerationRef.current = event.gen_id;
            }
            void audio.queue.enqueue({ genId: event.gen_id, seq: event.seq, data: event.data });
          }
          break;

        case 'subtitle':
          setCues((current) => [...current, event]);
          break;

        case 'action':
          // finish — конец тренировки. Приходит сразу, отчёт готовится уже
          // после него и сотруднику не показывается (см. SessionEndOverlay).
          if (event.action === 'finish') {
            audio?.queue.stopAll();
            setPlayback('idle');
            setFinished(true);
            break;
          }
          // Обычный переход (stay/next_stage) не обязан гасить индикатор —
          // это делает AudioQueue.onIdle, когда реплика реально доиграет.
          // Исключение — предохранитель: если очередь и так уже пуста
          // (ответ пришёл вовсе без звука, например при ошибке TTS),
          // action — единственный сигнал, что ход завершён.
          if (audio?.queue.isIdle) setPlayback('idle');
          break;

        case 'cancel':
          // Сервер подтвердил отмену. Локально мы её уже выполнили — это
          // подстраховка для случая, когда отмену инициировал не клиент.
          if (audio && event.gen_id !== genRef.current) audio.queue.stopAll();
          break;

        case 'report':
          // Отчёт сотруднику намеренно не показывается: это экран методиста
          // (§2), и он уже сохранён на сервере — здесь ловить нечего. Оверлей
          // конца тренировки поднят раньше, по action: finish.
          setPlayback('idle');
          break;

        case 'error':
          setError({ type: 'server', message: event.message, details: event.code });
          break;

        default:
          break;
      }
    },
    [audio],
  );

  // Сокет открывается только после клика: сервер, увидев подключение, сразу
  // начинает открывающую реплику (gateway/app/api/ws.py), и генерировать её
  // в звук, который браузер откажется играть, — значит выбросить её впустую.
  const { state: connection, send, sendUserMessage } = useSessionSocket({
    sessionId: started ? sessionId : null,
    onEvent: handleEvent,
    currentGeneration: () => genRef.current,
    onError: setError,
  });

  // Оверлей поднимает не эта функция, а ответное `action: finish` от сервера:
  // завершает сессию он, и локально угадывать этот момент незачем.
  const handleFinish = useCallback(() => {
    send({ type: 'finish_session' });
  }, [send]);

  const handleStart = useCallback(() => {
    if (!audio) return;

    // Разблокировка автоплея обязана произойти внутри обработчика клика:
    // отложенный resume() браузер уже не засчитает как жест пользователя.
    // Именно поэтому создание сессии ниже идёт ПОСЛЕ resume(), а не до: между
    // кликом и await'ом жест ещё «свежий», после — уже нет.
    void audio.audioCtx.resume().catch((cause: Error) => {
      setError({
        type: 'audio',
        message: 'Не удалось включить звук',
        details: cause.message,
      });
    });

    // Персонаж заговорит сам, как только сервер увидит подключение, — своё
    // поколение он заведёт первым же bump(), поэтому локально ждём gen 1.
    genRef.current = 1;
    audio.queue.startGeneration(genRef.current);
    setPlayback('thinking');

    gatewayApi
      .createSession(scenarioId)
      .then((response) => {
        setSessionId(response.session_id);
        // Сокет открывается по появлению sessionId вместе со started — до
        // этого момента открывать нечего.
        setStarted(true);
      })
      .catch((cause: Error) => {
        setPlayback('disconnected');
        setError({
          type: 'server',
          message: 'Не удалось начать сессию',
          details: cause.message,
        });
      });
  }, [audio, scenarioId]);

  useEffect(() => {
    if (connection === 'open') setPlayback((current) => (current === 'disconnected' ? 'idle' : current));
    if (connection === 'closed') setPlayback('disconnected');
  }, [connection]);

  // ----------------------------------------------------- отправка = перебивание

  const handleSubmit = useCallback(
    (text: string) => {
      // MessageComposer держит disabled, пока audio === null (аватар ещё
      // грузится) — это защита от невозможного состояния, а не рабочий путь.
      if (!audio) return;

      const interrupted = audio.clock.isPlaying ? genRef.current : null;

      // Шаг 1 (§6): локально и немедленно, без сетевого round-trip.
      cancelPlayback({
        queue: audio.queue,
        freezeSubtitles: () => setSubtitlesFrozen(true),
        resetFace: audio.resetFace,
      });

      // Шаг 2: сообщаем серверу, какое поколение перебиваем.
      sendUserMessage(text, interrupted, avatarModel.id);

      // Новое поколение сервер присвоит сам; локально готовим очередь принять
      // его чанки. Инкремент совпадает с серверным, потому что счётчик растёт
      // ровно на два события: открытие сессии (handleStart выставляет 1) и
      // каждую реплику пользователя. Открытие НОВОГО ЭТАПА поколения не
      // тратит — оно идёт тем же gen_id, что и ход, который его вызвал
      // (gateway/app/orchestrator/pipeline.py::_run_turn).
      genRef.current += 1;
      audio.queue.startGeneration(genRef.current);

      setTranscript((lines) => [...lines, { role: 'user', text }]);
      setCues([]);
      setSubtitlesFrozen(false);
      setPlayback('thinking');
    },
    [audio, avatarModel.id, sendUserMessage],
  );

  const switchAvatar = () => {
    if (!audio || playback !== 'idle') return;
    audio.queue.stopAll();
    audio.resetFace();
    setAudio(null);
    setAvatarModel((current) => {
      const currentIndex = AVATAR_MODEL_LIST.findIndex((model) => model.id === current.id);
      return AVATAR_MODEL_LIST[(currentIndex + 1) % AVATAR_MODEL_LIST.length];
    });
  };

  const nextAvatar =
    AVATAR_MODEL_LIST[
      (AVATAR_MODEL_LIST.findIndex((model) => model.id === avatarModel.id) + 1) %
        AVATAR_MODEL_LIST.length
    ];

  // ------------------------------------------------------------------ рендер

  return (
    <main className="session">
      <header className="session__header">
        <PlaybackIndicator state={playback} />
        {/* Обе стороны добавляли сюда свои элементы; обёртка одна —
            .session__header-actions удалён из styles.css как дубликат. */}
        <div className="session__controls">
          <button
            type="button"
            className="avatar-switch"
            onClick={switchAvatar}
            disabled={!audio || playback !== 'idle'}
          >
            Переключить на {nextAvatar.label}
          </button>
          <PushToTalkToggle enabled={pushToTalk} onChange={setPushToTalk} />
          <button
            type="button"
            className="session__finish"
            onClick={handleFinish}
            disabled={connection !== 'open' || finished}
          >
            Завершить
          </button>
        </div>
      </header>

      {error && (
        <p className="session__error" role="alert">
          {error.message}
        </p>
      )}

      <section className="session__main">
        <ChatPanel
          transcript={transcript}
          cues={cues}
          clock={audio?.clock ?? null}
          isAgentReplying={playback === 'speaking'}
        />

        <div className="session__stage">
          <TalkingHeadAvatar
            key={avatarModel.id}
            model={avatarModel}
            isSpeaking={playback === 'speaking'}
            onReady={handleAvatarReady}
            onError={handleAvatarError}
          />
          {audio && <Subtitles clock={audio.clock} cues={cues} frozen={subtitlesFrozen} />}
        </div>
      </section>

      <MessageComposer
        disabled={connection !== 'open' || !audio || finished}
        isAgentSpeaking={playback === 'speaking'}
        onSubmit={handleSubmit}
      />

      {/* Аватар грузится (13 МБ GLB) под оверлеем, поэтому он смонтирован
          всегда, а закрывает его этот слой — а не условный рендер сессии. */}
      {!started && <SessionStartOverlay ready={audio !== null} onStart={handleStart} />}
      {finished && <SessionEndOverlay />}
    </main>
  );
}

/** Токены персонажа дописываются в последнюю его реплику, а не создают новую. */
function appendAgentToken(lines: ChatTurn[], token: string): ChatTurn[] {
  const last = lines[lines.length - 1];
  if (last?.role === 'agent') {
    return [...lines.slice(0, -1), { ...last, text: last.text + token }];
  }
  return [...lines, { role: 'agent', text: token }];
}
