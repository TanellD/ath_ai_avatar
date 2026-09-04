import { useCallback, useEffect, useRef, useState } from 'react';

import { AudioQueue } from '@/audio/AudioQueue';
import { PlaybackClock } from '@/audio/PlaybackClock';
import { TalkingHeadAvatar, type AvatarPlaybackHandle } from '@/avatar/TalkingHeadAvatar';
import type { Emotion } from '@/contracts/events';

const SPEECH_WS_URL = import.meta.env.VITE_SPEECH_WS_URL ?? 'ws://localhost:8010';

const VOICES = [
  { value: 'Nina', label: 'Nina — яркая, молодая, дружелюбная' },
  { value: 'Piper', label: 'Piper — весёлая, яркая, энергичная' },
  { value: 'Reyna', label: 'Reyna — зрелая, театральная, эмоционально широкая' },
  { value: 'Reese', label: 'Reese — молодая, уверенная, решительная' },
  { value: 'Isla', label: 'Isla — живая, энергичная, британский акцент' },
] as const;

type EmotionIntensity = 'soft' | 'normal' | 'strong';

const INTENSITIES: Array<{ value: EmotionIntensity; label: string }> = [
  { value: 'soft', label: 'Мягкая' },
  { value: 'normal', label: 'Обычная' },
  { value: 'strong', label: 'Сильная' },
];

type SampleLength = 'short' | 'long';

const EMOTIONS: Array<{
  value: Emotion;
  label: string;
  sample: string;
  longSample: string;
}> = [
  {
    value: 'neutral',
    label: 'Нейтрально',
    sample: 'Давайте спокойно разберёмся в ситуации.',
    longSample: 'Хорошо, давайте спокойно разберёмся в ситуации, уточним основные условия и после этого решим, какой вариант подходит нам лучше всего.',
  },
  {
    value: 'friendly',
    label: 'Дружелюбно',
    sample: 'Хорошо, мне нравится ваше предложение.',
    longSample: 'Хорошо, мне нравится ваше предложение, и я действительно хочу найти удобное для всех решение, поэтому давайте вместе обсудим оставшиеся детали.',
  },
  {
    value: 'irritated',
    label: 'Раздражённо',
    sample: 'Вы снова не ответили на мой вопрос.',
    longSample: 'Послушайте, я уже несколько раз объяснила, что для меня важно получить конкретный ответ, но вы снова уходите от вопроса и предлагаете начать всё сначала.',
  },
  {
    value: 'angry',
    label: 'Сердито',
    sample: 'Нет, такие условия меня совершенно не устраивают.',
    longSample: 'Нет, такие условия меня совершенно не устраивают, потому что мы договаривались о другом, и всё же вы снова предлагаете переложить все риски на меня.',
  },
  {
    value: 'sad',
    label: 'Грустно',
    sample: 'Жаль, я ожидала совсем другого результата.',
    longSample: 'Жаль, я действительно надеялась, что мы сможем договориться, но теперь понимаю, что наши ожидания слишком сильно отличаются друг от друга.',
  },
  {
    value: 'excited',
    label: 'Воодушевлённо',
    sample: 'Вот это действительно отличная новость!',
    longSample: 'Вот это действительно отличная новость! Теперь мы можем запустить проект раньше, собрать первые результаты и, если всё получится, показать их всей команде уже на следующей неделе!',
  },
  {
    value: 'surprised',
    label: 'Удивлённо',
    sample: 'Правда? Такого поворота я совсем не ожидала!',
    longSample: 'Правда? Я совсем не ожидала, что вы согласитесь так быстро, поэтому мне даже нужно немного времени, чтобы осмыслить ваше предложение и проверить все детали.',
  },
];

function withEnhancedProsody(text: string): string {
  return text
    .replace(
      /(^|[.!?]\s*)(да|нет|хорошо|итак|конечно|пожалуй|послушайте|смотрите|жаль),\s*/giu,
      '$1$2, [pause] ',
    )
    .replace(
      /,\s+(но|однако|поэтому|зато|впрочем|и всё же)\b/giu,
      ', [pause] $1',
    );
}

interface LabRig extends AvatarPlaybackHandle {
  queue: AudioQueue;
}

interface TtsChunk {
  gen_id: number;
  seq: number;
  data: string;
  is_final: boolean;
}

export function EmotionLab() {
  const [emotion, setEmotion] = useState<Emotion>('neutral');
  const [intensity, setIntensity] = useState<EmotionIntensity>('strong');
  const [sampleLength, setSampleLength] = useState<SampleLength>('short');
  const [voice, setVoice] = useState<(typeof VOICES)[number]['value']>('Reese');
  const [enhancedProsody, setEnhancedProsody] = useState(true);
  const [text, setText] = useState(EMOTIONS[0].sample);
  const [rig, setRig] = useState<LabRig | null>(null);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const generationRef = useRef(0);

  const handleAvatarReady = useCallback((handle: AvatarPlaybackHandle) => {
    const clock = new PlaybackClock(handle.audioCtx);
    const queue = new AudioQueue(handle.audioCtx, clock, handle.destination, () =>
      setIsSpeaking(false),
    );
    setRig({ ...handle, queue });
  }, []);

  const handleAvatarError = useCallback((message: string) => setError(message), []);

  const stop = useCallback(() => {
    socketRef.current?.close();
    socketRef.current = null;
    rig?.queue.stopAll();
    rig?.resetFace();
    setIsSpeaking(false);
  }, [rig]);

  useEffect(() => stop, [stop]);

  const selectEmotion = (next: (typeof EMOTIONS)[number]) => {
    setEmotion(next.value);
    setText(sampleLength === 'long' ? next.longSample : next.sample);
    rig?.setEmotion(next.value);
  };

  const selectSampleLength = (next: SampleLength) => {
    setSampleLength(next);
    const current = EMOTIONS.find((item) => item.value === emotion) ?? EMOTIONS[0];
    setText(next === 'long' ? current.longSample : current.sample);
  };

  const speak = () => {
    if (!rig || !text.trim()) return;

    // Resume immediately while the click still counts as a user gesture.
    // Do not block the TTS connection on browsers that keep this promise pending.
    const audioResume = rig.audioCtx.resume();
    stop();
    setError(null);

    const genId = generationRef.current + 1;
    generationRef.current = genId;
    rig.queue.startGeneration(genId);
    rig.setEmotion(emotion);

    const socket = new WebSocket(`${SPEECH_WS_URL.replace(/\/$/, '')}/tts/stream`);
    socketRef.current = socket;
    setIsSpeaking(true);

    void audioResume.catch((cause: unknown) => {
      if (socketRef.current === socket) {
        socket.close();
        socketRef.current = null;
        setIsSpeaking(false);
        setError(
          `Браузер заблокировал звук: ${cause instanceof Error ? cause.message : String(cause)}`,
        );
      }
    });

    socket.onopen = () => {
      socket.send(
        JSON.stringify({
          gen_id: genId,
          seq: 0,
          text: text.trim(),
          voice_id: voice,
          emotion,
          intensity,
          enhanced_prosody: enhancedProsody,
        }),
      );
    };

    socket.onmessage = (message) => {
      const chunk = JSON.parse(message.data as string) as TtsChunk;
      if (chunk.gen_id !== generationRef.current) return;
      void rig.queue.enqueue({ genId: chunk.gen_id, seq: chunk.seq, data: chunk.data });
    };

    socket.onerror = () => {
      if (socketRef.current !== socket) return;
      setError(`Не удалось подключиться к speech-service: ${SPEECH_WS_URL}`);
      setIsSpeaking(false);
    };

    socket.onclose = () => {
      if (socketRef.current !== socket) return;
      socketRef.current = null;
      if (rig.queue.isIdle) setIsSpeaking(false);
    };
  };

  return (
    <main className="emotion-lab">
      <section className="emotion-lab__stage">
        <TalkingHeadAvatar
          isSpeaking={isSpeaking}
          onReady={handleAvatarReady}
          onError={handleAvatarError}
        />
      </section>

      <section className="emotion-lab__controls">
        <h1>Лаборатория эмоций</h1>
        <p>Выберите выражение, затем проверьте отдельно лицо или голос вместе с lip-sync.</p>

        <div className="emotion-lab__buttons">
          {EMOTIONS.map((item) => (
            <button
              type="button"
              className={item.value === emotion ? 'emotion-lab__emotion is-active' : 'emotion-lab__emotion'}
              key={item.value}
              onClick={() => selectEmotion(item)}
            >
              {item.label}
            </button>
          ))}
        </div>

        <label className="emotion-lab__field">
          Голос Soniox
          <select value={voice} onChange={(event) => setVoice(event.target.value as typeof voice)}>
            {VOICES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>

        <label className="emotion-lab__field">
          Интенсивность голоса
          <select
            value={intensity}
            onChange={(event) => setIntensity(event.target.value as EmotionIntensity)}
          >
            {INTENSITIES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>

        <label className="emotion-lab__field">
          Тестовая реплика
          <select
            value={sampleLength}
            onChange={(event) => selectSampleLength(event.target.value as SampleLength)}
          >
            <option value="short">Короткая</option>
            <option value="long">Длинная</option>
          </select>
        </label>

        <label className="emotion-lab__field">
          Реплика
          <textarea value={text} rows={4} onChange={(event) => setText(event.target.value)} />
        </label>

        <label className="emotion-lab__toggle">
          <input
            type="checkbox"
            checked={enhancedProsody}
            onChange={(event) => setEnhancedProsody(event.target.checked)}
          />
          Усиленная просодия
        </label>

        <p className="emotion-lab__meta">
          Emotion: <code>{emotion}</code> · Intensity: <code>{intensity}</code> · Voice:{' '}
          <code>{voice}</code>
        </p>

        {enhancedProsody && (
          <p className="emotion-lab__meta">
            В Soniox: <code>{withEnhancedProsody(text.trim())}</code>
          </p>
        )}

        <div className="emotion-lab__actions">
          <button type="button" onClick={() => rig?.setEmotion(emotion)} disabled={!rig}>
            Только лицо
          </button>
          <button type="button" onClick={() => void speak()} disabled={!rig || isSpeaking}>
            Произнести
          </button>
          <button type="button" onClick={stop} disabled={!isSpeaking}>
            Остановить
          </button>
        </div>

        {error && <p className="emotion-lab__error">{error}</p>}
      </section>
    </main>
  );
}
