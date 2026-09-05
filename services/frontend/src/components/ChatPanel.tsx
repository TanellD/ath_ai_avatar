/**
 * Панель истории диалога — слева от аватара.
 *
 * Свёрнутое состояние (по умолчанию, фиксированная небольшая высота):
 * видна только текущая реплика — вопрос сотрудника и ответ персонажа,
 * раскрывающийся текстом в такт голосу. Источник времени — PlaybackClock
 * (Claude.md §3), а не токены LLM: токены приходят быстрее речи, и если
 * показывать текст по ним, панель обгонит то, что реально прозвучало.
 * Данные для синхронизации — те же SubtitleEvent, что и у Subtitles.tsx,
 * только собранные в накопительный текст, а не в одну активную строку.
 *
 * Развёрнутое состояние (наведение или фокус клавиатурой — CSS :hover /
 * :focus-within, без JS-состояния): вся история, прокручиваемая. Текущая
 * реплика в развёрнутом виде — тот же самый синхронизированный элемент: по
 * завершении речи текст и так равен полному, разделять два представления
 * незачем.
 */

import { useEffect, useRef, useState } from 'react';

import type { PlaybackClock } from '@/audio/PlaybackClock';
import type { SubtitleEvent } from '@/contracts/events';
import { joinCueText } from '@/subtitles/cueText';

export interface ChatTurn {
  role: 'user' | 'agent';
  text: string;
}

interface Props {
  /** Все ходы, включая последний — если персонаж сейчас отвечает, его
   * текст в этом массиве уже есть (растёт по токенам), но панель для
   * ПОСЛЕДНЕЙ реплики персонажа использует не его, а синхронизированный
   * с аудио вариант ниже. */
  transcript: ChatTurn[];
  cues: SubtitleEvent[];
  clock: PlaybackClock | null;
  isAgentReplying: boolean;
}

export function ChatPanel({ transcript, cues, clock, isAgentReplying }: Props) {
  const [syncedText, setSyncedText] = useState('');
  const frameRef = useRef<number | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const lastIsLiveAgent = isAgentReplying && transcript.at(-1)?.role === 'agent';
  const history = lastIsLiveAgent ? transcript.slice(0, -1) : transcript;

  useEffect(() => {
    if (!clock || !lastIsLiveAgent) {
      setSyncedText('');
      return;
    }

    // requestAnimationFrame — каденция перерисовки, не источник времени:
    // на каждый кадр заново спрашиваем позицию у часов (clock.positionMs()),
    // не считаем сами. Тот же принцип, что в Subtitles.tsx.
    const tick = () => {
      const positionMs = clock.positionMs();
      const text = joinCueText(cues.filter((cue) => cue.start_ms <= positionMs));
      setSyncedText(text);
      frameRef.current = requestAnimationFrame(tick);
    };

    frameRef.current = requestAnimationFrame(tick);
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    };
  }, [clock, cues, lastIsLiveAgent]);

  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [history, syncedText]);

  return (
    <div className="chatpanel" tabIndex={0} aria-label="История диалога">
      <div className="chatpanel__list" ref={listRef}>
        {history.map((line, index) => (
          <p key={index} className={`chatpanel__line chatpanel__line--${line.role}`}>
            <span className="chatpanel__role">{line.role === 'user' ? 'Вы' : 'Персонаж'}:</span>{' '}
            {line.text}
          </p>
        ))}

        {lastIsLiveAgent && (
          <p className="chatpanel__line chatpanel__line--agent chatpanel__line--live">
            <span className="chatpanel__role">Персонаж:</span> {syncedText}
          </p>
        )}
      </div>
    </div>
  );
}
