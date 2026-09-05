import type { SubtitleEvent } from '@/contracts/events';

/** Собирает timestamp-фрагменты без пробелов внутри слов и сохраняет пробелы между фразами. */
export function joinCueText(cues: SubtitleEvent[]): string {
  return cues.reduce((text, cue) => {
    if (!text || !cue.text) return text + cue.text;
    if (/\s$/u.test(text) || /^\s/u.test(cue.text)) return text + cue.text;
    // Старый fallback присылает целые предложения без завершающего пробела.
    if (/[.!?…»)]$/u.test(text)) return `${text} ${cue.text}`;
    return text + cue.text;
  }, '');
}

/** Текущая, постепенно раскрывающаяся фраза для оверлея субтитров. */
export function currentCueSentence(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) return '';
  const boundaries = [...trimmed.matchAll(/[.!?…]/gu)].map((match) => match.index);
  let start = 0;
  const last = boundaries.at(-1);
  if (last !== undefined) {
    const boundaryBeforeCurrent = last === trimmed.length - 1 ? boundaries.at(-2) : last;
    if (boundaryBeforeCurrent !== undefined) start = boundaryBeforeCurrent + 1;
  }
  return trimmed.slice(start).trim();
}
