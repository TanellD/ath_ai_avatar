/**
 * Субтитры — Claude.md §3, §8.
 *
 * Позиция берётся из PlaybackClock, то есть из воспроизводимого аудио. Тайминги
 * в событии subtitle заданы ОТНОСИТЕЛЬНО начала аудио поколения (§7), поэтому
 * сравнивать их надо именно с positionMs() часов, а не с временем сессии.
 *
 * При перебивании субтитры **фиксируются** на текущей позиции, а не стираются
 * (§6, шаг 1): пользователь должен видеть, на чём персонажа оборвали.
 *
 * Лежат ПОВЕРХ аватара (см. .subtitles в styles.css). В потоке они занимали
 * постоянную полосу под лицом — пустую, пока персонаж молчит; отдать её
 * аватару было нельзя, иначе он менял бы размер на каждой реплике. Вне потока
 * обе задачи решаются разом.
 */

import { useEffect, useRef, useState } from 'react';

import type { PlaybackClock } from '@/audio/PlaybackClock';
import type { SubtitleEvent } from '@/contracts/events';
import { subtitleAt } from '@/subtitles/cueText';

interface Props {
  clock: PlaybackClock;
  cues: SubtitleEvent[];
  /** Заморожено при перебивании: перестаём двигаться, показываем последнее. */
  frozen: boolean;
  /** Ход закончился — только теперь позволено гасить текст по таймеру. */
  ended: boolean;
}

export function Subtitles({ clock, cues, frozen, ended }: Props) {
  const [text, setText] = useState('');
  const frameRef = useRef<number | null>(null);
  const boxRef = useRef<HTMLParagraphElement | null>(null);

  useEffect(() => {
    if (frozen) return;

    const tick = () => {
      setText(subtitleAt(cues, clock.positionMs(), ended));
      frameRef.current = requestAnimationFrame(tick);
    };

    frameRef.current = requestAnimationFrame(tick);
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    };
  }, [clock, cues, frozen, ended]);

  // Держим видимым конец фразы: высота ограничена тремя строками, длинная
  // реплика в неё не помещается. Прокручиваем, а не наращиваем блок.
  useEffect(() => {
    const box = boxRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [text]);

  if (!text) return null;

  return (
    <p
      ref={boxRef}
      className={frozen ? 'subtitles subtitles--frozen' : 'subtitles'}
      aria-live="polite"
    >
      {text}
    </p>
  );
}
