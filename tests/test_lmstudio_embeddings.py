import hashlib
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from evaluate_legal_embeddings import (
    EmbeddingEvaluationError,
    EvaluationCase,
    evaluate_cases,
    load_candidate_chunks,
    run_evaluation,
)
from lmstudio_embeddings import (
    EmbeddingClientError,
    LMStudioEmbeddingClient,
    cosine_similarity,
    rank_by_similarity,
)


class FakeResponse:
    def __init__(self, payload):
        if isinstance(payload, bytes):
            self.body = payload
        else:
            self.body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeEmbeddingClient:
    model = "test-embedding-model"
    base_url = "http://127.0.0.1:1234"

    def ensure_model_available(self):
        return (self.model, "another-model")

    def embed_texts(self, texts):
        if len(texts) != 6:
            raise AssertionError(f"expected one six-item batch, got {len(texts)}")
        return [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]


def chunk_record(chunk_id, text, chamber="1. Hukuk Dairesi"):
    decision_id = chunk_id.split(":", 1)[0]
    return {
        "id": chunk_id,
        "karar_id": decision_id,
        "chunk_metni": text,
        "chunk_metni_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "karakter_sayisi": len(text),
        "daire": chamber,
        "esas_no": "2024/1",
        "karar_no": "2025/2",
        "karar_tarihi": "01.02.2025",
        "veri_kalite_uyarilari": [],
    }


def write_jsonl(path, records):
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


class LMStudioEmbeddingTests(unittest.TestCase):
    def test_client_sends_utf8_batch_and_restores_index_order(self):
        response = {
            "object": "list",
            "model": "test-model",
            "data": [
                {"index": 1, "embedding": [0.0, 2.0, 0.0]},
                {"index": 0, "embedding": [1.0, 0.0, 0.0]},
            ],
        }
        client = LMStudioEmbeddingClient(model="test-model")
        captured = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse(response)

        with patch("lmstudio_embeddings.urlopen", side_effect=fake_urlopen):
            vectors = client.embed_texts(["Türkçe işçi", "tapu tescili"])

        self.assertEqual(vectors, [[1.0, 0.0, 0.0], [0.0, 2.0, 0.0]])
        payload = json.loads(captured["request"].data.decode("utf-8"))
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["input"], ["Türkçe işçi", "tapu tescili"])
        self.assertEqual(captured["request"].full_url, "http://127.0.0.1:1234/v1/embeddings")

    def test_model_list_and_availability_are_validated(self):
        client = LMStudioEmbeddingClient(model="embedding-model")
        response = {"data": [{"id": "chat-model"}, {"id": "embedding-model"}]}
        with patch(
            "lmstudio_embeddings.urlopen", return_value=FakeResponse(response)
        ):
            self.assertEqual(
                client.ensure_model_available(),
                ("chat-model", "embedding-model"),
            )

        missing_client = LMStudioEmbeddingClient(model="missing-model")
        with patch(
            "lmstudio_embeddings.urlopen", return_value=FakeResponse(response)
        ):
            with self.assertRaises(EmbeddingClientError):
                missing_client.ensure_model_available()

    def test_rejects_bad_embedding_counts_indexes_dimensions_and_numbers(self):
        client = LMStudioEmbeddingClient(model="test-model")
        bad_responses = (
            {"model": "test-model", "data": []},
            {
                "model": "test-model",
                "data": [
                    {"index": 0, "embedding": [1.0, 0.0]},
                    {"index": 0, "embedding": [0.0, 1.0]},
                ],
            },
            {
                "model": "test-model",
                "data": [
                    {"index": 0, "embedding": [1.0, 0.0]},
                    {"index": 1, "embedding": [1.0, 0.0, 0.0]},
                ],
            },
            {
                "model": "test-model",
                "data": [
                    {"index": 0, "embedding": [math.nan, 1.0]},
                    {"index": 1, "embedding": [1.0, 0.0]},
                ],
            },
            {
                "model": "test-model",
                "data": [
                    {"index": 0, "embedding": [0.0, 0.0]},
                    {"index": 1, "embedding": [1.0, 0.0]},
                ],
            },
        )
        for response in bad_responses:
            with self.subTest(response=response):
                with patch(
                    "lmstudio_embeddings.urlopen",
                    return_value=FakeResponse(response),
                ):
                    with self.assertRaises(EmbeddingClientError):
                        client.embed_texts(["bir", "iki"])

    def test_rejects_invalid_json_and_empty_input(self):
        client = LMStudioEmbeddingClient(model="test-model")
        with self.assertRaises(EmbeddingClientError):
            client.embed_texts([])
        with patch(
            "lmstudio_embeddings.urlopen", return_value=FakeResponse(b"not-json")
        ):
            with self.assertRaises(EmbeddingClientError):
                client.embed_texts(["metin"])

    def test_cosine_similarity_and_ranking(self):
        self.assertAlmostEqual(cosine_similarity([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(cosine_similarity([1, 0], [0, 1]), 0.0)
        self.assertAlmostEqual(cosine_similarity([1, 0], [-1, 0]), -1.0)
        ranking = rank_by_similarity(
            [1, 0], {"irrelevant": [0, 1], "relevant": [1, 0]}
        )
        self.assertEqual([item[0] for item in ranking], ["relevant", "irrelevant"])
        with self.assertRaises(EmbeddingClientError):
            cosine_similarity([1, 0], [1])
        with self.assertRaises(EmbeddingClientError):
            cosine_similarity([0, 0], [1, 0])

    def test_loads_exact_chunks_and_rejects_missing_or_corrupt_data(self):
        records = [
            chunk_record("d1:c0001", "İş sözleşmesi feshi."),
            chunk_record("d2:c0001", "Tapu iptali ve tescil."),
            chunk_record("d3:c0001", "Uyuşturucu madde ticareti."),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "chunks.jsonl"
            write_jsonl(source, records)
            loaded, count = load_candidate_chunks(
                source,
                ("d3:c0001", "d1:c0001"),
                expected_chunk_count=3,
            )
            self.assertEqual(list(loaded), ["d3:c0001", "d1:c0001"])
            self.assertEqual(count, 3)

            with self.assertRaises(EmbeddingEvaluationError):
                load_candidate_chunks(source, ("missing:c0001",))
            corrupt = list(records)
            corrupt[0] = dict(corrupt[0], chunk_metni_sha256="wrong")
            write_jsonl(source, corrupt)
            with self.assertRaises(EmbeddingEvaluationError):
                load_candidate_chunks(source, ("d1:c0001",))

    def test_evaluation_ranks_expected_real_topic_for_each_query(self):
        candidates = {
            "d1:c0001": chunk_record("d1:c0001", "İş sözleşmesi feshi."),
            "d2:c0001": chunk_record("d2:c0001", "Tapu iptali ve tescil."),
            "d3:c0001": chunk_record("d3:c0001", "Uyuşturucu ticareti."),
        }
        cases = (
            EvaluationCase("is", "İşe iade", "d1:c0001"),
            EvaluationCase("tapu", "Taşınmaz tescili", "d2:c0001"),
            EvaluationCase("ceza", "Uyuşturucu suçu", "d3:c0001"),
        )
        report = evaluate_cases(FakeEmbeddingClient(), candidates, cases)

        self.assertEqual(report["embedding"]["dimension"], 3)
        self.assertEqual(report["embedding"]["batch_input_count"], 6)
        self.assertEqual(report["summary"]["top1_accuracy_percent"], 100.0)
        self.assertTrue(report["summary"]["all_expected_above_irrelevant"])
        self.assertTrue(all(case["top_match_correct"] for case in report["cases"]))

    def test_run_evaluation_writes_atomic_report_with_source_hash(self):
        records = [
            chunk_record("d1:c0001", "İş sözleşmesi feshi."),
            chunk_record("d2:c0001", "Tapu iptali ve tescil."),
            chunk_record("d3:c0001", "Uyuşturucu madde ticareti."),
        ]
        cases = (
            EvaluationCase("is", "İşe iade", "d1:c0001"),
            EvaluationCase("tapu", "Taşınmaz tescili", "d2:c0001"),
            EvaluationCase("ceza", "Uyuşturucu suçu", "d3:c0001"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "chunks.jsonl"
            output = root / "evaluation.json"
            write_jsonl(source, records)
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            report = run_evaluation(
                source,
                output,
                expected_chunk_count=3,
                client=FakeEmbeddingClient(),
                candidate_ids=("d1:c0001", "d2:c0001", "d3:c0001"),
                cases=cases,
            )
            saved = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(saved, report)
        self.assertEqual(report["chunk_source"]["sha256"], source_hash)
        self.assertEqual(report["chunk_source"]["records"], 3)


if __name__ == "__main__":
    unittest.main()
