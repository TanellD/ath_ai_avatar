import unittest

from benchmarks.stt.scoring import aggregate, normalize, score_case, word_error_count


class ScoringTests(unittest.TestCase):
    def test_normalize_handles_case_punctuation_and_yo(self) -> None:
        self.assertEqual(normalize("Всё, ХОРОШО!"), "все хорошо")

    def test_word_error_count(self) -> None:
        self.assertEqual(word_error_count("один два три", "один четыре три"), (1, 3))

    def test_critical_entities_and_negations_are_scored_separately(self) -> None:
        case = {
            "id": "critical",
            "reference": "Нет, я не согласен на триста рублей",
            "critical_entities": ["триста рублей"],
            "negations": ["нет", "не"],
        }
        score = score_case(case, "Я согласен на триста рублей")
        result = aggregate([score])

        self.assertEqual(result["critical_entity_accuracy"], 1.0)
        self.assertEqual(result["lost_negations"], 2)
        self.assertEqual(result["added_negations"], 0)


if __name__ == "__main__":
    unittest.main()
