import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from evaluate_semantic_search_quality import (
    QualityCase,
    choose_recommended_configuration,
    evaluate_configuration,
)


class SemanticSearchQualityTests(unittest.TestCase):
    def setUp(self):
        self.cases = (
            QualityCase("relevant_1", "Birinci yeterince uzun sorgu", "d1"),
            QualityCase("relevant_2", "İkinci yeterince uzun sorgu", "d2"),
            QualityCase("out_of_domain", "Alan dışı yeterince uzun sorgu", None),
        )
        self.rankings = {
            "relevant_1": [
                {"karar_id": "x", "score": 0.72},
                {"karar_id": "d1", "score": 0.68},
            ],
            "relevant_2": [{"karar_id": "d2", "score": 0.62}],
            "out_of_domain": [{"karar_id": "z", "score": 0.59}],
        }

    def test_metrics_distinguish_relevant_recall_and_domain_rejection(self):
        metrics = evaluate_configuration(
            self.cases,
            self.rankings,
            top_k=3,
            threshold=0.60,
        )
        self.assertEqual(metrics["ilgili_recall"], 1.0)
        self.assertEqual(metrics["mrr"], 0.75)
        self.assertEqual(metrics["alan_disi_reddetme_orani"], 1.0)
        self.assertEqual(metrics["dengeli_dogruluk"], 1.0)

    def test_top_k_and_threshold_can_remove_an_expected_result(self):
        top_one = evaluate_configuration(
            self.cases,
            self.rankings,
            top_k=1,
            threshold=0.60,
        )
        high_threshold = evaluate_configuration(
            self.cases,
            self.rankings,
            top_k=3,
            threshold=0.65,
        )
        self.assertEqual(top_one["ilgili_recall"], 0.5)
        self.assertEqual(high_threshold["ilgili_recall"], 0.5)

    def test_recommendation_prefers_balanced_high_recall_setting(self):
        rows = [
            evaluate_configuration(
                self.cases,
                self.rankings,
                top_k=top_k,
                threshold=threshold,
            )
            for top_k in (1, 3)
            for threshold in (0.60, 0.65)
        ]
        recommendation = choose_recommended_configuration(rows)
        self.assertEqual(recommendation["top_k"], 3)
        self.assertEqual(recommendation["minimum_score"], 0.60)


if __name__ == "__main__":
    unittest.main()
