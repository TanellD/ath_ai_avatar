/**
 * Редактор сценария — Claude.md §2, §7.
 *
 * Закрывает TODO из MethodistScenarios.tsx и последнюю непроверенную гипотезу
 * продукта (docs/PRODUCT_hypotheses.md, Г7): «методисту достаточно
 * декларативного сценария, программист для новой тренировки не нужен». До
 * этого экрана сценарий заводился только руками через PUT, и проверить Г7 было
 * нечем.
 *
 * Форма собрана из готового кита (`.demo-form`, `.field`, `.is-full`, `.req`)
 * — он лежит в styles/clarity-ui.css полностью реализованным и до сих пор не
 * использовался ни одним экраном. Свои классы заведены только под то, чего в
 * ките нет: строки-повторители этапов и критериев.
 *
 * Один и тот же компонент обслуживает /scenarios/new и /scenarios/:id/edit.
 * Разница ровно в двух вещах: откуда берётся начальное состояние и можно ли
 * трогать id. При правке id заблокирован — PUT адресуется по нему, и правка
 * поля создала бы копию вместо переименования.
 *
 * Шаблоны здесь не правятся: их копируют (`scenarioApi.copy` в списке), иначе
 * первый же прогон испортит эталон для всей команды — то же решение, что
 * зафиксировано в шапке MethodistScenarios.tsx.
 */

import { useCallback, useEffect, useId, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { aiApi, scenarioApi } from '@/api/client';
import type { Mood, Persona, RubricItem, Scenario, Stage } from '@/contracts/events';
import { hasIssues, validateScenario } from '@/scenario/validate';
import type { ScenarioIssues } from '@/scenario/validate';

const MOODS: { value: Mood; label: string }[] = [
  { value: 'neutral', label: 'Нейтральное' },
  { value: 'irritated', label: 'Раздражённое' },
  { value: 'friendly', label: 'Дружелюбное' },
];

/** Значения по умолчанию — из контракта (`ath_contracts/scenario.py`). */
function emptyStage(index: number): Stage {
  return {
    id: `stage_${index + 1}`,
    goal: '',
    agent_opening: '',
    completion_criteria: '',
    max_turns: 4,
  };
}

function emptyRubricItem(index: number): RubricItem {
  return { id: `criterion_${index + 1}`, name: '', description: '', scale: 5, weight: 1 };
}

function emptyScenario(): Scenario {
  return {
    id: '',
    title: '',
    persona: {
      name: '',
      role: '',
      character: '',
      mood: 'neutral',
      difficulty: 3,
      voice_id: null,
    },
    stages: [emptyStage(0)],
    rubric: [emptyRubricItem(0)],
    tags: [],
  };
}

interface FieldProps {
  label: string;
  error?: string;
  hint?: string;
  full?: boolean;
  required?: boolean;
  children: (id: string) => ReactNode;
}

/**
 * Подпись + контрол + ошибка под ним. Ошибку показываем рядом с полем, а не
 * общим списком наверху: в форме на два десятка полей список «где-то что-то не
 * так» заставляет искать глазами.
 */
function Field({ label, error, hint, full, required, children }: FieldProps) {
  const id = useId();
  return (
    <div className={full ? 'field is-full' : 'field'}>
      <label className={required ? 'req' : undefined} htmlFor={id}>
        {label}
      </label>
      {children(id)}
      {hint && <p className="modal-hint">{hint}</p>}
      {error && <p className="scenario-form__error">{error}</p>}
    </div>
  );
}

export function ScenarioEditor() {
  const { scenarioId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const isEdit = Boolean(scenarioId);

  /**
   * «Копировать» — это /scenarios/new?from=<id>: та же форма, заполненная
   * исходником, но с пустым идентификатором. Копия делается сохранением
   * нового сценария, а не отдельной ручкой копирования: так методист сам
   * называет копию, а не переименовывает потом сгенерированный id (после
   * сохранения id уже не меняется).
   */
  const copyFrom = isEdit ? null : searchParams.get('from');
  const source = scenarioId ?? copyFrom;

  const [scenario, setScenario] = useState<Scenario>(emptyScenario);
  const [takenIds, setTakenIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(Boolean(source));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const [brief, setBrief] = useState('');
  const [generating, setGenerating] = useState<'draft' | 'rubric' | null>(null);
  const [genError, setGenError] = useState<string | null>(null);

  useEffect(() => {
    if (!source) return;
    setLoading(true);
    scenarioApi
      .get(source)
      .then((loaded) =>
        setScenario(
          copyFrom ? { ...loaded, id: '', title: `${loaded.title} (копия)` } : loaded,
        ),
      )
      .catch((cause: Error) => setError(cause.message))
      .finally(() => setLoading(false));
  }, [source, copyFrom]);

  // Список нужен только новому сценарию — чтобы не затереть чужой одноимённый.
  useEffect(() => {
    if (isEdit) return;
    scenarioApi
      .list()
      .then((items) => setTakenIds(items.map((item) => item.id)))
      .catch(() => setTakenIds([]));
  }, [isEdit]);

  const issues = useMemo<ScenarioIssues>(
    () => validateScenario(scenario, isEdit ? {} : { takenIds }),
    [scenario, isEdit, takenIds],
  );
  // До первой попытки сохранить форма молчит: подсвечивать пустые поля сразу
  // после открытия — значит встретить методиста красным экраном.
  const shown: ScenarioIssues = submitted ? issues : {};

  // Критерии выводятся из персонажа и этапов: по пустой форме модель
  // придумает рубрику к несуществующему разговору.
  const canDraftRubric =
    Boolean(scenario.title.trim())
    && Boolean(scenario.persona.name.trim())
    && scenario.stages.every((stage) => stage.goal.trim() && stage.completion_criteria.trim());
  const rubricFilled = scenario.rubric.some((item) => item.name.trim() || item.description.trim());

  const patch = useCallback((update: Partial<Scenario>) => {
    setScenario((current) => ({ ...current, ...update }));
  }, []);

  const patchPersona = useCallback((update: Partial<Persona>) => {
    setScenario((current) => ({ ...current, persona: { ...current.persona, ...update } }));
  }, []);

  const patchStage = useCallback((index: number, update: Partial<Stage>) => {
    setScenario((current) => ({
      ...current,
      stages: current.stages.map((stage, i) => (i === index ? { ...stage, ...update } : stage)),
    }));
  }, []);

  const patchRubric = useCallback((index: number, update: Partial<RubricItem>) => {
    setScenario((current) => ({
      ...current,
      rubric: current.rubric.map((item, i) => (i === index ? { ...item, ...update } : item)),
    }));
  }, []);

  /**
   * Черновик уезжает в форму, а не в базу: методист смотрит и правит перед
   * сохранением. Ответственность за методику остаётся у человека — модель
   * ускоряет заполнение, но не решает, чему учить.
   */
  const handleDraft = () => {
    setGenerating('draft');
    setGenError(null);
    aiApi
      .draftScenario(brief, scenario.stages.length, scenario.rubric.length)
      .then((draft) => {
        // id не трогаем: его задаёт человек, и он же адрес страницы.
        setScenario((current) => ({ ...current, ...draft }));
        setSubmitted(false);
      })
      .catch((cause: Error) => setGenError(cause.message))
      .finally(() => setGenerating(null));
  };

  const handleRubric = () => {
    setGenerating('rubric');
    setGenError(null);
    aiApi
      .draftRubric(scenario.title, scenario.persona, scenario.stages, scenario.rubric.length)
      .then((items) => {
        patch({ rubric: items });
        setSubmitted(false);
      })
      .catch((cause: Error) => setGenError(cause.message))
      .finally(() => setGenerating(null));
  };

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    setError(null);

    if (hasIssues(issues)) return;

    setSaving(true);
    scenarioApi
      .save({
        ...scenario,
        id: scenario.id.trim(),
        title: scenario.title.trim(),
        persona: {
          ...scenario.persona,
          // Пустая строка в voice_id значит «голос по умолчанию», а контракт
          // ждёт для этого null.
          voice_id: scenario.persona.voice_id?.trim() ? scenario.persona.voice_id.trim() : null,
        },
      })
      .then((saved) => navigate(`/scenarios/${saved.id}`))
      .catch((cause: Error) => setError(cause.message))
      .finally(() => setSaving(false));
  };

  if (loading) return <p className="page">Загружаем сценарий…</p>;

  return (
    <main className="page page--wide">
      <section className="card hero-card hero-card--compact">
        <span className="eyebrow">{isEdit ? 'Правка' : 'Новый сценарий'}</span>
        <h1>{isEdit ? scenario.title || 'Сценарий' : 'Создать сценарий'}</h1>
        <p className="lead">
          Персонаж, этапы разговора и рубрика оценки. Всё, что здесь заполнено, попадёт
          сотруднику в тренировку и методисту в отчёт.
        </p>
      </section>

      <form className="scenario-form" onSubmit={handleSubmit} noValidate>
        {/* Только на пустом бланке. У копии содержание уже есть, и кнопка
            «заменить всё» рядом с ним — ловушка, а не помощь. */}
        {!isEdit && !copyFrom && (
          <section className="card report__section">
            <span className="eyebrow">Черновик</span>
            <h2>Начать с описания</h2>
            <p className="admin__hint">
              Опишите тренировку парой фраз — персонаж, этапы и рубрика заполнятся сами.
              Это черновик: он попадёт в форму, а не в библиотеку, и правится как обычно.
            </p>
            <div className="demo-form">
              <Field label="Что тренируем" full>
                {(id) => (
                  <textarea
                    id={id}
                    value={brief}
                    rows={3}
                    placeholder="Менеджер продаёт CRM для логистики начальнику отдела закупок. Тот говорит, что у них уже всё работает и бюджета нет."
                    onChange={(event) => setBrief(event.target.value)}
                  />
                )}
              </Field>
            </div>
            <div className="scenario-form__generate">
              <button
                type="button"
                className="btn btn-gray"
                onClick={handleDraft}
                disabled={generating !== null || !brief.trim()}
              >
                {generating === 'draft' ? 'Собираем черновик…' : 'Развернуть черновик'}
              </button>
              <span className="modal-hint">
                Займёт до минуты: сценарий целиком собирает сильная модель.
                Этапов и критериев будет столько же, сколько сейчас в форме.
              </span>
            </div>
          </section>
        )}

        <section className="card report__section">
          <span className="eyebrow">Основное</span>
          <h2>Что это за тренировка</h2>
          <div className="demo-form">
            <Field
              label="Идентификатор"
              required
              error={shown.id}
              hint={
                isEdit
                  ? 'У сохранённого сценария не меняется: по нему собраны ссылки и отчёты'
                  : 'Попадёт в адрес страницы: /scenarios/objection_price'
              }
            >
              {(id) => (
                <input
                  id={id}
                  type="text"
                  value={scenario.id}
                  disabled={isEdit}
                  placeholder="objection_price"
                  onChange={(event) => patch({ id: event.target.value })}
                />
              )}
            </Field>

            <Field label="Название" required error={shown.title}>
              {(id) => (
                <input
                  id={id}
                  type="text"
                  value={scenario.title}
                  placeholder="Отработка возражения «дорого»"
                  onChange={(event) => patch({ title: event.target.value })}
                />
              )}
            </Field>

            <Field
              label="Теги"
              full
              hint="Через запятую. По ним методист ищет сценарий в списке"
            >
              {(id) => (
                <input
                  id={id}
                  type="text"
                  value={scenario.tags.join(', ')}
                  placeholder="продажи, возражения, цена"
                  onChange={(event) =>
                    patch({
                      tags: event.target.value
                        .split(',')
                        .map((tag) => tag.trim())
                        .filter(Boolean),
                    })
                  }
                />
              )}
            </Field>
          </div>
        </section>

        <section className="card report__section">
          <span className="eyebrow">Персонаж</span>
          <h2>С кем разговаривает сотрудник</h2>
          <div className="demo-form">
            <Field label="Имя" required error={shown['persona.name']}>
              {(id) => (
                <input
                  id={id}
                  type="text"
                  value={scenario.persona.name}
                  placeholder="Ирина"
                  onChange={(event) => patchPersona({ name: event.target.value })}
                />
              )}
            </Field>

            <Field label="Роль" required error={shown['persona.role']}>
              {(id) => (
                <input
                  id={id}
                  type="text"
                  value={scenario.persona.role}
                  placeholder="закупщик среднего бизнеса"
                  onChange={(event) => patchPersona({ role: event.target.value })}
                />
              )}
            </Field>

            <Field
              label="Манера"
              full
              required
              error={shown['persona.character']}
              hint="Как себя ведёт: перебивает, торгуется, уходит от ответа"
            >
              {(id) => (
                <textarea
                  id={id}
                  value={scenario.persona.character}
                  placeholder="скептична, перебивает, торгуется"
                  onChange={(event) => patchPersona({ character: event.target.value })}
                />
              )}
            </Field>

            <Field label="Настроение" hint="Меняется между прогонами одного сценария">
              {(id) => (
                <select
                  id={id}
                  value={scenario.persona.mood}
                  onChange={(event) => patchPersona({ mood: event.target.value as Mood })}
                >
                  {MOODS.map((mood) => (
                    <option key={mood.value} value={mood.value}>
                      {mood.label}
                    </option>
                  ))}
                </select>
              )}
            </Field>

            <Field label="Сложность" error={shown['persona.difficulty']} hint="От 1 до 5">
              {(id) => (
                <input
                  id={id}
                  type="number"
                  min={1}
                  max={5}
                  value={scenario.persona.difficulty}
                  onChange={(event) =>
                    patchPersona({ difficulty: Number(event.target.value) })
                  }
                />
              )}
            </Field>

            <Field
              label="Голос"
              full
              hint="Идентификатор голоса у провайдера TTS. Пусто — голос по умолчанию"
            >
              {(id) => (
                <input
                  id={id}
                  type="text"
                  value={scenario.persona.voice_id ?? ''}
                  onChange={(event) => patchPersona({ voice_id: event.target.value })}
                />
              )}
            </Field>
          </div>
        </section>

        <section className="card report__section">
          <span className="eyebrow">Этапы</span>
          <h2>Как строится разговор</h2>
          <p className="admin__hint">
            Переход между этапами делает код, а не модель: она только относит ответ
            сотрудника к «зачтено / неполно / не по теме». Поэтому критерий прохождения —
            формулировка для классификатора, и сотруднику он не показывается.
          </p>
          {shown.stages && <p className="scenario-form__error">{shown.stages}</p>}

          {scenario.stages.map((stage, index) => (
            <div key={index} className="scenario-form__row">
              <div className="scenario-form__row-head">
                <span className="bento-pill">{index + 1}</span>
                <button
                  type="button"
                  className="scenario-form__remove"
                  onClick={() =>
                    patch({ stages: scenario.stages.filter((_, i) => i !== index) })
                  }
                  disabled={scenario.stages.length === 1}
                  aria-label={`Удалить этап ${index + 1}`}
                >
                  Удалить
                </button>
              </div>
              <div className="demo-form">
                <Field label="Идентификатор" required error={shown[`stages.${index}.id`]}>
                  {(id) => (
                    <input
                      id={id}
                      type="text"
                      value={stage.id}
                      onChange={(event) => patchStage(index, { id: event.target.value })}
                    />
                  )}
                </Field>

                <Field
                  label="Ходов на этап"
                  error={shown[`stages.${index}.max_turns`]}
                  hint="Страховка от зацикливания"
                >
                  {(id) => (
                    <input
                      id={id}
                      type="number"
                      min={1}
                      value={stage.max_turns}
                      onChange={(event) =>
                        patchStage(index, { max_turns: Number(event.target.value) })
                      }
                    />
                  )}
                </Field>

                <Field
                  label="Цель этапа"
                  full
                  required
                  error={shown[`stages.${index}.goal`]}
                  hint="Видна сотруднику в подсказке по этапу"
                >
                  {(id) => (
                    <input
                      id={id}
                      type="text"
                      value={stage.goal}
                      placeholder="Установить контакт и выяснить контекст"
                      onChange={(event) => patchStage(index, { goal: event.target.value })}
                    />
                  )}
                </Field>

                <Field
                  label="Чем персонаж открывает этап"
                  full
                  required
                  error={shown[`stages.${index}.agent_opening`]}
                >
                  {(id) => (
                    <textarea
                      id={id}
                      value={stage.agent_opening}
                      placeholder="Здравствуйте. У меня десять минут, давайте по делу."
                      onChange={(event) =>
                        patchStage(index, { agent_opening: event.target.value })
                      }
                    />
                  )}
                </Field>

                <Field
                  label="Критерий прохождения"
                  full
                  required
                  error={shown[`stages.${index}.completion_criteria`]}
                  hint="Формулировка для классификатора. Сотруднику не показывается"
                >
                  {(id) => (
                    <textarea
                      id={id}
                      value={stage.completion_criteria}
                      placeholder="Сотрудник представился и задал минимум один открытый вопрос"
                      onChange={(event) =>
                        patchStage(index, { completion_criteria: event.target.value })
                      }
                    />
                  )}
                </Field>
              </div>
            </div>
          ))}

          <button
            type="button"
            className="scenario-form__add"
            onClick={() =>
              patch({ stages: [...scenario.stages, emptyStage(scenario.stages.length)] })
            }
          >
            Добавить этап
          </button>
        </section>

        <section className="card report__section">
          <span className="eyebrow">Рубрика</span>
          <h2>Что проверяется</h2>
          <p className="admin__hint">
            Под каждый критерий отчёт обязан дать дословную цитату из реплики сотрудника —
            без неё оценку нельзя проверить быстро. Чем длиннее рубрика, тем выше шанс, что
            модель пропустит критерий и отчёт будет отбракован целиком.
          </p>
          <div className="scenario-form__generate">
            <button
              type="button"
              className="btn btn-gray"
              onClick={handleRubric}
              disabled={generating !== null || !canDraftRubric}
            >
              {generating === 'rubric' ? 'Подбираем критерии…' : 'Заполнить критерии'}
            </button>
            <span className="modal-hint">
              {canDraftRubric
                ? rubricFilled
                  ? 'Заменит все критерии ниже — заполненное сейчас пропадёт'
                  : 'По названию, персонажу и этапам выше'
                : 'Сначала заполните название, персонажа и этапы'}
            </span>
          </div>
          {shown.rubric && <p className="scenario-form__error">{shown.rubric}</p>}

          {scenario.rubric.map((item, index) => (
            <div key={index} className="scenario-form__row">
              <div className="scenario-form__row-head">
                <span className="bento-pill">{index + 1}</span>
                <button
                  type="button"
                  className="scenario-form__remove"
                  onClick={() =>
                    patch({ rubric: scenario.rubric.filter((_, i) => i !== index) })
                  }
                  disabled={scenario.rubric.length === 1}
                  aria-label={`Удалить критерий ${index + 1}`}
                >
                  Удалить
                </button>
              </div>
              <div className="demo-form">
                <Field label="Идентификатор" required error={shown[`rubric.${index}.id`]}>
                  {(id) => (
                    <input
                      id={id}
                      type="text"
                      value={item.id}
                      onChange={(event) => patchRubric(index, { id: event.target.value })}
                    />
                  )}
                </Field>

                <Field label="Название" required error={shown[`rubric.${index}.name`]}>
                  {(id) => (
                    <input
                      id={id}
                      type="text"
                      value={item.name}
                      placeholder="Выявление потребности"
                      onChange={(event) => patchRubric(index, { name: event.target.value })}
                    />
                  )}
                </Field>

                <Field
                  label="Описание"
                  full
                  required
                  error={shown[`rubric.${index}.description`]}
                  hint="Видно сотруднику до старта — «что вообще здесь оценивают»"
                >
                  {(id) => (
                    <textarea
                      id={id}
                      value={item.description}
                      placeholder="Задавал открытые вопросы, не перешёл к презентации раньше времени"
                      onChange={(event) =>
                        patchRubric(index, { description: event.target.value })
                      }
                    />
                  )}
                </Field>

                <Field label="Шкала" error={shown[`rubric.${index}.scale`]} hint="Не меньше 2">
                  {(id) => (
                    <input
                      id={id}
                      type="number"
                      min={2}
                      value={item.scale}
                      onChange={(event) =>
                        patchRubric(index, { scale: Number(event.target.value) })
                      }
                    />
                  )}
                </Field>

                <Field
                  label="Вес"
                  error={shown[`rubric.${index}.weight`]}
                  hint="Во сколько раз критерий важнее остальных"
                >
                  {(id) => (
                    <input
                      id={id}
                      type="number"
                      min={0.1}
                      step={0.1}
                      value={item.weight}
                      onChange={(event) =>
                        patchRubric(index, { weight: Number(event.target.value) })
                      }
                    />
                  )}
                </Field>
              </div>
            </div>
          ))}

          <button
            type="button"
            className="scenario-form__add"
            onClick={() =>
              patch({ rubric: [...scenario.rubric, emptyRubricItem(scenario.rubric.length)] })
            }
          >
            Добавить критерий
          </button>
        </section>

        {genError && (
          <p className="scenario-form__error" role="alert">
            Не удалось собрать черновик: {genError}. Форма не изменилась — попробуйте ещё раз.
          </p>
        )}
        {error && (
          <p className="scenario-form__error" role="alert">
            Не удалось сохранить: {error}
          </p>
        )}
        {submitted && hasIssues(issues) && (
          <p className="scenario-form__error" role="alert">
            Проверьте подсвеченные поля — сценарий пока не сохранён.
          </p>
        )}

        <div className="scenario-form__actions">
          <Link
            to={isEdit && scenarioId ? `/scenarios/${scenarioId}` : '/scenarios'}
            className="btn btn-gray"
          >
            Отмена
          </Link>
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving ? 'Сохраняем…' : 'Сохранить сценарий'}
          </button>
        </div>
      </form>
    </main>
  );
}
