import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from evaluate_day20_system import (
    Day20EvaluationError,
    EvaluationCase,
    analyze_retrieval_errors,
    choose_recommended_configuration,
    decision_rankings,
    evaluate_configuration,
    load_evaluation_cases,
)
from qdrant_vector_store import SearchHit


class Day20EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.cases = (
            EvaluationCase(
                "relevant_1",
                "iş hukuku",
                "İş sözleşmesi geçerli neden olmadan feshedildi.",
                ("d1",),
                "7. Hukuk Dairesi",
                True,
            ),
            EvaluationCase(
                "relevant_2",
                "ceza hukuku",
                "Mahkûmiyet eksik soruşturmayla kurulmuş olabilir.",
                ("d2",),
                "9. Ceza Dairesi",
                False,
            ),
            EvaluationCase(
                "out_of_domain",
                "idare hukuku",
                "İdari işlemin iptali için mahkemeye başvurulacak.",
                (),
                None,
                False,
            ),
        )
        self.rankings = {
            "relevant_1": [
                {"karar_id": "x", "score": 0.72},
                {"karar_id": "d1", "score": 0.68},
            ],
            "relevant_2": [{"karar_id": "d2", "score": 0.62}],
            "out_of_domain": [{"karar_id": "z", "score": 0.59}],
        }

    def test_metrics_recommendation_and_error_analysis(self):
        comparisons = [
            evaluate_configuration(
                self.cases,
                self.rankings,
                top_k=top_k,
                threshold=threshold,
            )
            for top_k in (1, 3)
            for threshold in (0.60, 0.65)
        ]
        recommendation = choose_recommended_configuration(comparisons)

        self.assertEqual(recommendation["top_k"], 3)
        self.assertEqual(recommendation["minimum_score"], 0.60)
        self.assertEqual(recommendation["capa_recall"], 1.0)
        self.assertEqual(recommendation["alan_disi_reddetme_orani"], 1.0)
        self.assertEqual(recommendation["alan_disi_sifir_sonuc_orani"], 1.0)

        errors = analyze_retrieval_errors(
            self.cases,
            self.rankings,
            top_k=1,
            threshold=0.65,
        )
        by_id = {row["case_id"]: row for row in errors}
        self.assertFalse(by_id["relevant_1"]["basarili"])
        self.assertIn("top_k", by_id["relevant_1"]["neden"])
        self.assertFalse(by_id["relevant_2"]["basarili"])
        self.assertIn("eşiğinin", by_id["relevant_2"]["neden"])
        self.assertTrue(by_id["out_of_domain"]["basarili"])

    def test_decision_rankings_deduplicate_chunks(self):
        hits = (
            SearchHit("d1:c1", 0.9, {"karar_id": "d1", "daire": "7"}),
            SearchHit("d1:c2", 0.8, {"karar_id": "d1", "daire": "7"}),
            SearchHit("d2:c1", 0.7, {"karar_id": "d2", "daire": "9"}),
        )
        rankings = decision_rankings(hits)
        self.assertEqual([row["karar_id"] for row in rankings], ["d1", "d2"])
        self.assertEqual(rankings[0]["chunk_id"], "d1:c1")

    def test_single_out_of_domain_hit_is_rejected_by_rag_source_floor(self):
        rankings = dict(self.rankings)
        rankings["out_of_domain"] = [{"karar_id": "z", "score": 0.61}]

        metrics = evaluate_configuration(
            self.cases,
            rankings,
            top_k=3,
            threshold=0.60,
        )

        self.assertEqual(metrics["alan_disi_reddetme_orani"], 1.0)
        self.assertEqual(metrics["alan_disi_sifir_sonuc_orani"], 0.0)
        out_of_domain = next(
            row for row in metrics["cases"] if row["case_id"] == "out_of_domain"
        )
        self.assertTrue(out_of_domain["alan_disi_reddedildi"])
        self.assertFalse(out_of_domain["sifir_sonuc"])

    def test_loads_and_rejects_invalid_test_sets(self):
        cases = []
        for index in range(10):
            in_domain = index < 5
            cases.append(
                {
                    "case_id": f"case_{index}",
                    "hukuk_alani": "iş hukuku" if in_domain else "idare hukuku",
                    "query": f"Geçerli uzunlukta değerlendirme sorgusu {index}",
                    "expected_decision_ids": [f"d{index}"] if in_domain else [],
                    "expected_chamber": "7. Hukuk Dairesi" if in_domain else None,
                    "rag_test": index == 0,
                }
            )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.json"
            path.write_text(
                json.dumps({"version": "1.0", "cases": cases}, ensure_ascii=False),
                encoding="utf-8",
            )
            version, digest, loaded = load_evaluation_cases(path)
            self.assertEqual(version, "1.0")
            self.assertEqual(len(digest), 64)
            self.assertEqual(len(loaded), 10)

            cases[1]["case_id"] = "case_0"
            path.write_text(
                json.dumps({"version": "1.0", "cases": cases}, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(Day20EvaluationError, "Tekrarlanan"):
                load_evaluation_cases(path)


if __name__ == "__main__":
    unittest.main()
