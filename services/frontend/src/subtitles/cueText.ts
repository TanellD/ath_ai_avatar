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

/** Сколько субтитры держатся на экране после конца ХОДА. */
export const SUBTITLE_LINGER_MS = 1000;

/**
 * Что показывать в оверлее на данной позиции аудио. Пустая строка — скрыть.
 *
 * Отдельной функцией, а не внутри компонента, по той же причине, что и
 * `agentLines`: здесь живут ошибки, которые глазами не поймать, и обе уже
 * случались. Сперва компонент вызывал setText ТОЛЬКО когда было что показать,
 * и ветки «стереть» не было вовсе — после конца реплики её текст висел до
 * следующей. Потом гашение сделали по одной лишь тишине дольше секунды — и
 * субтитры стали пропадать ПОСРЕДИ речи: TTS отдаёт её чанками, пауза между
 * ними легко больше секунды, а следующего cue в массиве ещё нет.
 *
 * Отсюда `ended`: пока ход идёт, последняя фраза остаётся на экране, сколько
 * бы ни длилась пауза. Гаснет она только после конца хода.
 */
export function subtitleAt(cues: SubtitleEvent[], positionMs: number, ended = false): string {
  const visible = cues.filter((cue) => cue.start_ms <= positionMs);
  if (!visible.length) return '';

  const lastEnd = visible.reduce((end, cue) => Math.max(end, cue.end_ms), 0);
  if (ended && positionMs > lastEnd + SUBTITLE_LINGER_MS) return '';

  return currentCueSentence(joinCueText(visible));
}
