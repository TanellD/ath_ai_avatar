/**
 * Подстановка деталей в бриф — зеркало `ath_contracts.render_text`.
 *
 * На клиенте она нужна ровно в одном месте: на превью сценария
 * (`/scenarios/:id`), где сессии ещё нет и подставлять нечего, кроме
 * объявленных методистом примеров. Это сознательно бесплатная и мгновенная
 * страница — «что это за кейс» не повод ходить в модель.
 *
 * Настоящие детали прогона подставляет gateway при создании сессии, и клиент
 * получает их уже готовыми в ответе `createSession`.
 *
 * Шаблон обязан совпадать с питоновским `\{(\w+)\}`: разойдясь, стороны
 * подставят разное, и сотрудник увидит фигурные скобки в тексте. `\w` в JS —
 * только латиница, поэтому кириллические ключи слотов сюда не подходят; их и
 * не бывает, ai-service приводит id к слагу.
 */

import type { ScenarioSlot } from '@/contracts/events';

const PLACEHOLDER = /\{(\w+)\}/g;

/**
 * Неизвестный плейсхолдер остаётся как есть — намеренно: пустое место в тексте
 * не отличить от задумки, а «{company}» видно глазами и чинится.
 */
export function renderBriefing(text: string, values: Record<string, string>): string {
  return text.replace(PLACEHOLDER, (match, name: string) => values[name] ?? match);
}

export function slotDefaults(slots: ScenarioSlot[]): Record<string, string> {
  return Object.fromEntries(slots.map((slot) => [slot.id, slot.example]));
}
