/**
 * Субтитры — Claude.md §3, §8.
 *
 * Позиция берётся из PlaybackClock, то есть из воспроизводимого аудио. Тайминги
 * в событии subtitle заданы ОТНОСИТЕЛЬНО начала аудио поколения (§7), поэтому
 * сравнивать их надо именно с positionMs() часов, а не с временем сессии.
 *
 * При перебивании субтитры **фиксируются** на текущей позиции, а не стираются
 * (§6, шаг 1): пользователь должен видеть, на чём персонажа оборвали.
 */

import { useEffect, useRef, useState } from 'react';

import type { PlaybackClock } from '@/audio/PlaybackClock';
import type { SubtitleEvent } from '@/contracts/events';
import { currentCueSentence, joinCueText } from '@/subtitles/cueText';

interface Props {
  clock: PlaybackClock;
  cues: SubtitleEvent[];
  /** Заморожено при перебивании: перестаём двигаться, показываем последнее. */
  frozen: boolean;
}

export function Subtitles({ clock, cues, frozen }: Props) {
  const [text, setText] = useState('');
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    if (frozen) return;

    const tick = () => {
      const positionMs = clock.positionMs();
      const visible = cues.filter((cue) => cue.start_ms <= positionMs);
      if (visible.length) setText(currentCueSentence(joinCueText(visible)));
      frameRef.current = requestAnimationFrame(tick);
    };

    frameRef.current = requestAnimationFrame(tick);
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    };
  }, [clock, cues, frozen]);

  if (!text) return null;

  return (
    <p className={frozen ? 'subtitles subtitles--frozen' : 'subtitles'} aria-live="polite">
      {text}
    </p>
  );
}
