/**
 * Склейка токенов персонажа в реплики чата.
 *
 * Отдельным модулем, а не внутри TraineeSession: логика чистая и её нужно
 * покрыть тестом, а импорт страницы тянет за собой 3D-аватар с
 * AudioWorkletNode, которого в тестовой среде нет.
 */

import type { ChatTurn } from '@/components/ChatPanel';

/**
 * Токены дописываются в последнюю реплику персонажа — но только пока это ТА
 * ЖЕ реплика (`continues`, т.е. то же поколение).
 *
 * Персонаж может заговорить дважды подряд без реплики пользователя между
 * ними: инициатива при долгом молчании сотрудника (SilenceFollowup) — как раз
 * такой случай. Раньше проверялась только роль последней строки, и второй
 * ответ дописывался в конец первого. Дальше склеенный пузырь становился
 * «живым» в ChatPanel, а живой пузырь рисуется из cues, которые таймер
 * молчания только что очистил, — готовое сообщение на глазах пустело.
 */
export function appendAgentToken(
  lines: ChatTurn[],
  token: string,
  continues: boolean,
): ChatTurn[] {
  const last = lines[lines.length - 1];
  if (continues && last?.role === 'agent') {
    return [...lines.slice(0, -1), { ...last, text: last.text + token }];
  }
  return [...lines, { role: 'agent', text: token }];
}
