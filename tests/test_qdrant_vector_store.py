import hashlib
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.http import models

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from evaluate_legal_embeddings import EvaluationCase
from qdrant_vector_store import (
    PAYLOAD_SCHEMA,
    QdrantVectorStore,
    VectorStoreError,
    build_chunk_payload,
    point_id_for_chunk,
    validate_vector,
)
from validate_qdrant_vector_store import run_day14_validation


class FakeEmbeddingClient:
    model = "test-embedding-model"
    base_url = "http://127.0.0.1:1234"

    def ensure_model_available(self):
        return (self.model,)

    def embed_texts(self, texts):
        if len(texts) != 6:
            raise AssertionError(f"expected six inputs, got {len(texts)}")
        return [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]


def chunk_record(chunk_id, text, chamber="1. Hukuk Dairesi", order=1):
    decision_id = chunk_id.split(":", 1)[0]
    return {
        "id": chunk_id,
        "karar_id": decision_id,
        "chunk_sirasi": order,
        "toplam_chunk": 1,
        "daire": chamber,
        "karar_turu": "hukuk",
        "esas_no": "2024/1",
        "karar_no": "2025/2",
        "karar_tarihi": "01.02.2025",
        "baslik": f"{chamber} örnek karar",
        "chunk_metni": text,
        "chunk_metni_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "karakter_sayisi": len(text),
        "veri_kalite_uyarilari": [],
        "veri_kalite_durumu": "gecerli",
        "metin_2000_karakter_sinirinda": False,
        "kaynak": "test-corpus",
        "kaynak_url": "https://example.test/corpus",
        "kaynak_lisans": "CC BY 4.0",
        "kaynak_kayit_id": decision_id,
    }


def write_jsonl(path, records):
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


class QdrantVectorStoreTests(unittest.TestCase):
    def setUp(self):
        self.client = QdrantClient(location=":memory:")
        self.store = QdrantVectorStore(
            client=self.client,
            collection_name="test_chunks",
            vector_size=3,
            embedding_model="test-embedding-model",
        )

    def tearDown(self):
        self.client.close()

    def test_collection_has_cosine_dimension_and_payload_schema(self):
        created = self.store.ensure_collection()
        existing = self.store.ensure_collection()

        self.assertTrue(created["created"])
        self.assertFalse(existing["created"])
        self.assertEqual(created["vector_size"], 3)
        self.assertEqual(created["distance"], "Cosine")
        self.assertEqual(created["embedding_model"], "test-embedding-model")
        self.assertEqual(created["payload_schema"], PAYLOAD_SCHEMA)

    def test_rejects_incompatible_existing_collection(self):
        self.client.create_collection(
            collection_name="wrong",
            vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE),
            metadata={
                "schema_version": "1.0",
                "embedding_model": "test-embedding-model",
                "vector_size": 2,
                "distance": "Cosine",
                "payload_schema": PAYLOAD_SCHEMA,
            },
        )
        wrong_store = QdrantVectorStore(
            client=self.client,
            collection_name="wrong",
            vector_size=3,
            embedding_model="test-embedding-model",
        )
        with self.assertRaises(VectorStoreError):
            wrong_store.ensure_collection()

    def test_upsert_read_search_delete_and_restore(self):
        self.store.ensure_collection()
        records = [
            chunk_record("d1:c0001", "İş sözleşmesi feshi ve işe iade."),
            chunk_record("d2:c0001", "Tapu iptali ve tescil davası."),
            chunk_record("d3:c0001", "Uyuşturucu madde ticareti suçu."),
        ]
        vectors = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]

        self.assertEqual(self.store.upsert_chunks(records, vectors), 3)
        self.assertEqual(self.store.count(), 3)
        retrieved = self.store.get_chunk("d2:c0001")
        self.assertEqual(retrieved["chunk_metni"], records[1]["chunk_metni"])
        self.assertEqual(retrieved["embedding_dimension"], 3)

        hits = self.store.search([0.9, 0.1, 0.0], limit=3)
        self.assertEqual([hit.chunk_id for hit in hits], [
            "d1:c0001",
            "d2:c0001",
            "d3:c0001",
        ])
        self.assertGreater(hits[0].score, hits[1].score)

        self.assertTrue(self.store.delete_chunk("d3:c0001"))
        self.assertFalse(self.store.delete_chunk("d3:c0001"))
        self.assertEqual(self.store.count(), 2)
        self.store.upsert_chunks([records[2]], [vectors[2]])
        self.assertEqual(self.store.count(), 3)

    def test_payload_and_vectors_are_strictly_validated(self):
        valid = chunk_record("d1:c0001", "Geçerli karar metni.")
        payload = build_chunk_payload(
            valid,
            embedding_model="test-model",
            vector_size=3,
        )
        self.assertEqual(payload["chunk_id"], "d1:c0001")
        self.assertEqual(set(payload), set(PAYLOAD_SCHEMA))

        corrupt = dict(valid, chunk_metni_sha256="wrong")
        with self.assertRaises(VectorStoreError):
            build_chunk_payload(corrupt, embedding_model="test-model", vector_size=3)
        with self.assertRaises(VectorStoreError):
            validate_vector([1.0, 0.0], expected_size=3)
        with self.assertRaises(VectorStoreError):
            validate_vector([math.nan, 0.0, 1.0], expected_size=3)
        with self.assertRaises(VectorStoreError):
            validate_vector([0.0, 0.0, 0.0], expected_size=3)

    def test_point_ids_are_stable_unique_uuids(self):
        first = point_id_for_chunk("d1:c0001")
        self.assertEqual(first, point_id_for_chunk("d1:c0001"))
        self.assertNotEqual(first, point_id_for_chunk("d1:c0002"))
        self.assertEqual(len(first), 36)
        with self.assertRaises(VectorStoreError):
            point_id_for_chunk("")

    def test_rejects_duplicate_ids_and_count_mismatch(self):
        self.store.ensure_collection()
        record = chunk_record("d1:c0001", "Karar metni.")
        with self.assertRaises(VectorStoreError):
            self.store.upsert_chunks([record], [])
        with self.assertRaises(VectorStoreError):
            self.store.upsert_chunks(
                [record, record],
                [[1, 0, 0], [1, 0, 0]],
            )

    def test_day14_runner_writes_verified_report(self):
        records = [
            chunk_record("d1:c0001", "İş sözleşmesi feshi ve işe iade."),
            chunk_record("d2:c0001", "Tapu iptali ve tescil davası."),
            chunk_record("d3:c0001", "Uyuşturucu madde ticareti suçu."),
        ]
        cases = (
            EvaluationCase("is", "İşe iade", "d1:c0001"),
            EvaluationCase("tapu", "Tapu tescili", "d2:c0001"),
            EvaluationCase("ceza", "Uyuşturucu suçu", "d3:c0001"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "chunks.jsonl"
            report_path = root / "report.json"
            write_jsonl(source, records)
            report = run_day14_validation(
                source,
                root / "unused-qdrant-path",
                report_path,
                expected_chunk_count=3,
                expected_vector_size=3,
                collection_name="day14_test",
                candidate_ids=("d1:c0001", "d2:c0001", "d3:c0001"),
                cases=cases,
                embedding_client=FakeEmbeddingClient(),
                qdrant_client=self.client,
            )
            saved = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(saved, report)
        self.assertEqual(report["summary"]["correct_top_matches"], 3)
        self.assertEqual(report["summary"]["top1_accuracy_percent"], 100.0)
        self.assertTrue(report["summary"]["all_crud_operations_verified"])
        self.assertEqual(report["operations"]["count_after_upsert"], 3)
        self.assertEqual(report["operations"]["count_after_delete"], 2)
        self.assertEqual(report["operations"]["count_after_restore"], 3)


if __name__ == "__main__":
    unittest.main()
