"""Сборка и проверка отчёта — Claude.md §7.

Модель может вернуть синтаксически валидный JSON и при этом сломать главное
свойство отчёта — проверяемость. Здесь стоит защита от двух конкретных отказов.

**Пересказ вместо цитаты.** Промпт требует цитировать дословно, но требование в
промпте — не гарантия. При текстовом вводе транскрипт есть истина, поэтому
цитату можно проверить механически: `evidence` обязана быть подстрокой одной из
реплик сотрудника. Это дешёвая и абсолютно надёжная проверка.

**Она станет нестрогой при переходе на голос.** Транскрипт STT перестанет быть
истиной, и точное вхождение начнёт ложно срабатывать на ошибках распознавания.
Тогда сравнение придётся ослабить до нечёткого — но не убирать: расхождение
цитаты и транскрипта останется сигналом, просто перестанет быть однозначным.
См. docs/stt-phase.md.
"""

import re

from ath_contracts import CriterionScore, Report, Scenario, Turn, TurnRole

from app.core.logging import get_logger

log = get_logger(__name__)


class InvalidReportError(ValueError):
    """Отчёт не прошёл проверку и не должен показываться методисту."""


def _normalize(text: str) -> str:
    """Приведение к виду, устойчивому к пробелам и кавычкам-ёлочкам."""
    text = text.replace("«", '"').replace("»", '"').replace("ё", "е")
    return re.sub(r"\s+", " ", text).strip().lower()


def build_report(
    session_id: str,
    scenario: Scenario,
    transcript: list[Turn],
    raw: dict,
    duration_sec: int,
    stages_completed: int,
    stages_total: int,
    model: str = "",
) -> Report:
    """Собрать Report из ответа модели, проверив цитаты.

    `model` — чем посчитано; попадает в отчёт, чтобы оценку заглушкой можно
    было отличить от настоящей, не вчитываясь в вердикт.
    """
    user_texts = [_normalize(t.text) for t in transcript if t.role is TurnRole.USER]
    weights = {item.id: item.weight for item in scenario.rubric}

    scores: list[CriterionScore] = []
    for entry in raw.get("scores", []):
        score = CriterionScore.model_validate(entry)
        _verify_evidence(score, user_texts)
        scores.append(score)

    _verify_coverage(scores, scenario)

    return Report(
        session_id=session_id,
        scenario_id=scenario.id,
        model=model,
        verdict=raw["verdict"],
        total_score=_weighted_total(scores, weights),
        scores=scores,
        transcript=transcript,
        duration_sec=duration_sec,
        stages_completed=stages_completed,
        stages_total=stages_total,
    )


def _verify_evidence(score: CriterionScore, user_texts: list[str]) -> None:
    """Цитата обязана дословно встречаться в репликах сотрудника."""
    needle = _normalize(score.evidence)
    if not needle:
        raise InvalidReportError(f"критерий {score.criterion_id}: пустая цитата")

    if not any(needle in text for text in user_texts):
        raise InvalidReportError(
            f"критерий {score.criterion_id}: цитата {score.evidence!r} отсутствует "
            "в репликах сотрудника — модель пересказала вместо того, чтобы процитировать"
        )


def _verify_coverage(scores: list[CriterionScore], scenario: Scenario) -> None:
    """Каждый критерий рубрики оценён ровно один раз."""
    expected = {item.id for item in scenario.rubric}
    actual = [score.criterion_id for score in scores]

    if len(actual) != len(set(actual)):
        raise InvalidReportError("один и тот же критерий оценён дважды")

    missing = expected - set(actual)
    if missing:
        raise InvalidReportError(f"не оценены критерии: {', '.join(sorted(missing))}")


def _weighted_total(scores: list[CriterionScore], weights: dict[str, float]) -> float:
    """Средневзвешенный балл.

    Считаем здесь, а не берём из ответа модели: арифметика — не та задача, где
    стоит доверять языковой модели, а методист сверит сумму первым делом.
    """
    if not scores:
        return 0.0

    total_weight = sum(weights.get(s.criterion_id, 1.0) for s in scores)
    weighted = sum(s.score * weights.get(s.criterion_id, 1.0) for s in scores)
    return round(weighted / total_weight, 2) if total_weight else 0.0
