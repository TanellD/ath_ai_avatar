/**
 * Применение сгенерированного черновика к форме редактора — Claude.md §7.
 *
 * Отдельный чистый модуль, а не логика внутри `ScenarioEditor.tsx`, по тому же
 * принципу, что `validate.ts`: без него `applyDraft`/`draftContext` живут
 * внутри компонента и не накрываются тестом.
 */

import type { ScenarioDraft } from '@/api/client';
import type { Scenario } from '@/contracts/events';

/**
 * Черновик заменяет всё, что видно и правится в форме, но не то, что форма не
 * показывает как поле генерации:
 *
 * - `id` — его задаёт человек, он же адрес страницы редактора и ключ в БД.
 *   Генерация лишь ПРЕДЛАГАЕТ id (`draft.suggested_id`) и только пока поле
 *   пустое — на чистом бланке или если методист сам его стёр. Если id уже
 *   заполнен (правка, копия, вторая генерация после того, как методист его
 *   вписал), трогать его нельзя — иначе слетит адрес существующего сценария.
 * - `brief` — это вход генерации, а не её результат. Затереть его тем же
 *   вызовом, который его же читает, значит потерять историю «из чего вырос
 *   этот сценарий» после первой правки.
 */
export function applyDraft(current: Scenario, draft: ScenarioDraft): Scenario {
  return {
    ...current,
    id: current.id.trim() ? current.id : draft.suggested_id ?? current.id,
    title: draft.title,
    persona: draft.persona,
    stages: draft.stages,
    rubric: draft.rubric,
    tags: draft.tags,
    briefing: draft.briefing,
    slots: draft.slots,
  };
}

/**
 * Пустая заготовка формы (один `emptyStage()`, один `emptyRubricItem()`,
 * персонаж без единого заполненного поля) — то же самое, что «формы ещё нет».
 * Отправлять её как `current` смысла нет: генерации не на что опираться, а
 * округление до неё в промпте (`app/scenario/prompts.py::_current_block`)
 * само отфильтрует пустые поля — здесь она нужна только для текста подсказки
 * в `ScenarioEditor.tsx` («заполнятся сами» против «пересоберём с опорой на
 * то, что уже есть»).
 */
export function isBlank(scenario: Scenario): boolean {
  const persona = scenario.persona;
  return (
    !scenario.title.trim() &&
    !persona.name.trim() &&
    !persona.role.trim() &&
    !persona.character.trim() &&
    !scenario.briefing.trim() &&
    scenario.stages.every(
      (stage) =>
        !stage.goal.trim() && !stage.agent_opening.trim() && !stage.completion_criteria.trim(),
    ) &&
    scenario.rubric.every((item) => !item.name.trim() && !item.description.trim())
  );
}

/** Что отправить как `current` в `POST /scenario/draft` — `null` на пустой форме. */
export function draftContext(scenario: Scenario): ScenarioDraft | null {
  if (isBlank(scenario)) return null;

  return {
    title: scenario.title,
    persona: scenario.persona,
    stages: scenario.stages,
    rubric: scenario.rubric,
    tags: scenario.tags,
    briefing: scenario.briefing,
    slots: scenario.slots,
  };
}
