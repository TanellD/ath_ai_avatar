/**
 * Подсказка по этапу — docs/bugs_front.md №15.
 *
 * Показывает только `stage.goal` — что вообще происходит на этапе.
 * `completion_criteria` сюда не попадает ни при каких условиях: это
 * критерий для классификатора (Claude.md §5), а не чек-лист правильных
 * фраз для сотрудника. Тот же принцип, что и в промпте персонажа
 * (app/character/prompts.py: `build_classifier_system` видит критерий,
 * `build_character_system` — нет).
 */

import { useEffect, useRef, useState } from 'react';

interface Props {
  goal: string;
}

export function StageHint({ goal }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    const onClickOutside = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };

    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('mousedown', onClickOutside);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('mousedown', onClickOutside);
    };
  }, [open]);

  return (
    <div className="stage-hint" ref={rootRef}>
      <button
        type="button"
        className="stage-hint__toggle"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        aria-label="Подсказка по этапу"
      >
        ?
      </button>
      {open && (
        <div className="stage-hint__popover" role="tooltip">
          {goal}
        </div>
      )}
    </div>
  );
}
