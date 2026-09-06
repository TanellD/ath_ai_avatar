/**
 * Цитата под баллом — Claude.md §7, главная гипотеза продукта.
 *
 *   «Каждый балл обязан иметь evidence — дословную цитату из реплики
 *    пользователя. Без неё методист не может проверить оценку быстро, начнёт
 *    слушать запись целиком, и экономия времени исчезнет.»
 *
 * В текстовой фазе цитата — это ровно то, что напечатал человек, поэтому она
 * самодостаточна: методист сверяет её глазами с транскриптом за секунды.
 *
 * [STT] С голосом цитата станет выдержкой из транскрипта STT, который ошибается
 * на именах, числах и ценах — то есть ровно на содержании балла. Тогда под
 * цитатой появятся две вещи, для которых здесь оставлено место:
 *   - кнопка воспроизведения фрагмента (audio_ref, ≈5 с);
 *   - флаг низкой уверенности (stt_confidence) — «перепроверь на слух».
 * См. docs/stt-phase.md.
 *
 * Вёрстка — по карточкам критериев из front/Дашборд методиста.dc.html.
 */

import type { CriterionScore } from '@/contracts/events';

const LOW_CONFIDENCE = 0.75;

interface Props {
  score: CriterionScore;
  criterionName: string;
  scale: number;
}

export function EvidenceQuote({ score, criterionName, scale }: Props) {
  const lowConfidence = score.stt_confidence !== null && score.stt_confidence < LOW_CONFIDENCE;

  return (
    <li className="evidence">
      <div className="evidence__header">
        <span className="evidence__criterion">{criterionName}</span>
        <span className="evidence__score">
          {score.score}
          <small> / {scale}</small>
        </span>
      </div>

      <div className="evidence__quote-box">
        <blockquote className="evidence__quote">«{score.evidence}»</blockquote>

        {/* [STT] Здесь появится <button> воспроизведения фрагмента по audio_ref. */}
        {score.audio_ref !== null && (
          <button className="evidence__play" type="button" disabled>
            Прослушать фрагмент
          </button>
        )}
      </div>

      {score.comment && <p className="evidence__comment">{score.comment}</p>}

      {lowConfidence && (
        <p className="evidence__warning">Низкая уверенность распознавания — перепроверьте на слух.</p>
      )}
    </li>
  );
}
