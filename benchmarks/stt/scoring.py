"""Provider-neutral quality scoring for the team's annotated Russian corpus."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

TOKEN_RE = re.compile(r"[^\w]+", re.UNICODE)


def normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower().replace("ё", "е")
    return " ".join(TOKEN_RE.sub(" ", normalized).split())


def word_error_count(reference: str, hypothesis: str) -> tuple[int, int]:
    expected = normalize(reference).split()
    actual = normalize(hypothesis).split()
    previous = list(range(len(actual) + 1))
    for row, expected_word in enumerate(expected, start=1):
        current = [row]
        for column, actual_word in enumerate(actual, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (expected_word != actual_word),
                )
            )
        previous = current
    return previous[-1], len(expected)


def phrase_count(text: str, phrase: str) -> int:
    tokens = normalize(text).split()
    phrase_tokens = normalize(phrase).split()
    if not phrase_tokens:
        return 0
    width = len(phrase_tokens)
    return sum(tokens[index : index + width] == phrase_tokens for index in range(len(tokens)))


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    word_errors: int
    reference_words: int
    critical_correct: int
    critical_total: int
    lost_negations: int
    added_negations: int


def score_case(case: dict[str, Any], hypothesis: str) -> CaseScore:
    reference = str(case["reference"])
    errors, words = word_error_count(reference, hypothesis)
    entities = [str(item) for item in case.get("critical_entities", [])]
    negations = [str(item) for item in case.get("negations", [])]

    expected_negations = sum(phrase_count(reference, item) for item in negations)
    actual_negations = sum(phrase_count(hypothesis, item) for item in negations)
    return CaseScore(
        case_id=str(case["id"]),
        word_errors=errors,
        reference_words=words,
        critical_correct=sum(phrase_count(hypothesis, item) > 0 for item in entities),
        critical_total=len(entities),
        lost_negations=max(0, expected_negations - actual_negations),
        added_negations=max(0, actual_negations - expected_negations),
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def aggregate(scores: list[CaseScore]) -> dict[str, Any]:
    errors = sum(item.word_errors for item in scores)
    words = sum(item.reference_words for item in scores)
    critical_correct = sum(item.critical_correct for item in scores)
    critical_total = sum(item.critical_total for item in scores)
    return {
        "cases": len(scores),
        "wer": errors / words if words else 0.0,
        "critical_entity_accuracy": (
            critical_correct / critical_total if critical_total else None
        ),
        "lost_negations": sum(item.lost_negations for item in scores),
        "added_negations": sum(item.added_negations for item in scores),
        "details": [asdict(item) for item in scores],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--hypotheses", type=Path, required=True)
    args = parser.parse_args()

    cases = {str(item["id"]): item for item in read_jsonl(args.manifest)}
    hypotheses = {str(item["id"]): str(item["text"]) for item in read_jsonl(args.hypotheses)}
    missing = sorted(cases.keys() - hypotheses.keys())
    if missing:
        raise SystemExit(f"Missing hypotheses for: {', '.join(missing)}")

    result = aggregate([score_case(case, hypotheses[case_id]) for case_id, case in cases.items()])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
