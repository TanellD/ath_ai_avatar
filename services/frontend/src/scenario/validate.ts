/**
 * Проверка сценария перед сохранением — Claude.md §7.
 *
 * Отдельный чистый модуль, а не проверки внутри формы: сюда вынесено ровно то,
 * чего backend НЕ проверяет, и каждая строка здесь закрывает конкретную
 * поломку, а не «на всякий случай».
 *
 * Контракт (`ath_contracts/scenario.py`) объявляет только числовые границы
 * (`ge`/`le`/`gt`) и `min_length=1` на списках. Всё остальное — голый `str`,
 * поэтому пустое название и дубликат id сохраняются штатно и ломаются потом:
 *
 *   - дубликат `stage.id` — `StageMachine` строит `{stage.id: stage}` и ищет
 *     позицию через `.index()`. Дубликат тихо схлопывает словарь, и переходы
 *     по этапам начинают вести не туда. Молча, без единой ошибки;
 *   - дубликат `rubric[].id` — `report_builder._verify_coverage` отбракует
 *     отчёт («один и тот же критерий оценён дважды»), но уже ПОСЛЕ целой
 *     пройденной сессии: сотрудник отговорил, а оценки нет;
 *   - занятый `id` — `PUT /scenarios/{id}` это upsert, он молча перезапишет
 *     чужой сценарий. Сервер тут помочь не может: он не знает, методист
 *     создаёт новый или сохраняет существующий. Защита возможна только здесь.
 *
 * Числовые границы продублированы намеренно: получить 422 после заполнения
 * длинной формы — худший из возможных способов узнать, что вес должен быть
 * больше нуля.
 */

import type { Scenario } from '@/contracts/events';

/** Путь к полю → текст ошибки. Путь совпадает с ключом в форме: `stages.0.id`. */
export type ScenarioIssues = Record<string, string>;

export interface ValidateOptions {
  /**
   * id существующих сценариев. Передаётся только при создании: при правке
   * собственный id сценария, разумеется, занят им самим.
   */
  takenIds?: readonly string[];
}

/** Становится сегментом URL и первичным ключом `VARCHAR(128)`. */
const ID_PATTERN = /^[a-z0-9_-]{1,128}$/;

const ID_HINT = 'Латиница в нижнем регистре, цифры, дефис и подчёркивание';

function requireText(
  issues: ScenarioIssues,
  path: string,
  value: string,
  label: string,
): void {
  if (!value.trim()) issues[path] = `${label}: заполните поле`;
}

/** Первое повторяющееся значение помечается вторым и далее вхождением. */
function markDuplicateIds(
  issues: ScenarioIssues,
  items: readonly { id: string }[],
  prefix: string,
  label: string,
): void {
  const seen = new Set<string>();
  items.forEach((item, index) => {
    const id = item.id.trim();
    if (!id) return;
    if (seen.has(id)) issues[`${prefix}.${index}.id`] = `${label} «${id}» уже есть выше`;
    seen.add(id);
  });
}

export function validateScenario(
  scenario: Scenario,
  options: ValidateOptions = {},
): ScenarioIssues {
  const issues: ScenarioIssues = {};

  const id = scenario.id.trim();
  if (!id) issues.id = 'Идентификатор: заполните поле';
  else if (!ID_PATTERN.test(id)) issues.id = ID_HINT;
  else if (options.takenIds?.includes(id)) {
    issues.id = `Сценарий «${id}» уже существует — сохранение затрёт его`;
  }

  requireText(issues, 'title', scenario.title, 'Название');

  requireText(issues, 'persona.name', scenario.persona.name, 'Имя персонажа');
  requireText(issues, 'persona.role', scenario.persona.role, 'Роль');
  requireText(issues, 'persona.character', scenario.persona.character, 'Манера');
  if (!Number.isInteger(scenario.persona.difficulty)
    || scenario.persona.difficulty < 1
    || scenario.persona.difficulty > 5) {
    issues['persona.difficulty'] = 'Сложность — целое число от 1 до 5';
  }

  if (scenario.stages.length === 0) issues.stages = 'Нужен хотя бы один этап';
  scenario.stages.forEach((stage, index) => {
    const path = `stages.${index}`;
    if (!stage.id.trim()) issues[`${path}.id`] = 'Идентификатор этапа: заполните поле';
    else if (!ID_PATTERN.test(stage.id.trim())) issues[`${path}.id`] = ID_HINT;

    requireText(issues, `${path}.goal`, stage.goal, 'Цель этапа');
    requireText(issues, `${path}.agent_opening`, stage.agent_opening, 'Реплика персонажа');
    requireText(
      issues,
      `${path}.completion_criteria`,
      stage.completion_criteria,
      'Критерий прохождения',
    );
    if (!Number.isInteger(stage.max_turns) || stage.max_turns < 1) {
      issues[`${path}.max_turns`] = 'Ходов на этап — целое число не меньше 1';
    }
  });
  markDuplicateIds(issues, scenario.stages, 'stages', 'Этап с идентификатором');

  if (scenario.rubric.length === 0) issues.rubric = 'Нужен хотя бы один критерий';
  scenario.rubric.forEach((item, index) => {
    const path = `rubric.${index}`;
    if (!item.id.trim()) issues[`${path}.id`] = 'Идентификатор критерия: заполните поле';
    else if (!ID_PATTERN.test(item.id.trim())) issues[`${path}.id`] = ID_HINT;

    requireText(issues, `${path}.name`, item.name, 'Название критерия');
    requireText(issues, `${path}.description`, item.description, 'Описание критерия');
    if (!Number.isInteger(item.scale) || item.scale < 2) {
      issues[`${path}.scale`] = 'Шкала — целое число не меньше 2';
    }
    if (!(item.weight > 0)) issues[`${path}.weight`] = 'Вес должен быть больше нуля';
  });
  markDuplicateIds(issues, scenario.rubric, 'rubric', 'Критерий с идентификатором');

  return issues;
}

export function hasIssues(issues: ScenarioIssues): boolean {
  return Object.keys(issues).length > 0;
}
