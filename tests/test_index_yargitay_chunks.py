import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from qdrant_client import QdrantClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from index_yargitay_chunks import (
    Day15IndexingError,
    load_index_state,
    run_day15_indexing,
    scan_chunk_source,
)
from lmstudio_embeddings import EmbeddingClientError


class FakeEmbeddingClient:
    model = "test-embedding-model"
    base_url = "http://127.0.0.1:1234"

    def __init__(self):
        self.batches = []

    def ensure_model_available(self):
        return (self.model,)

    def embed_texts(self, texts):
        self.batches.append(list(texts))
        return [
            [1.0, float((len(text) % 7) + 1), float(index + 1)]
            for index, text in enumerate(texts)
        ]


class FailingEmbeddingClient(FakeEmbeddingClient):
    def embed_texts(self, texts):
        self.batches.append(list(texts))
        raise EmbeddingClientError("temporary embedding failure")


def chunk_record(index):
    text = f"Yargıtay karar parçası {index}: uyuşmazlığın hukuki değerlendirmesi."
    chunk_id = f"d{index:04d}:c0001"
    return {
        "id": chunk_id,
        "karar_id": f"d{index:04d}",
        "chunk_sirasi": 1,
        "toplam_chunk": 1,
        "daire": "1. Hukuk Dairesi",
        "karar_turu": "hukuk",
        "esas_no": f"2024/{index}",
        "karar_no": f"2025/{index}",
        "karar_tarihi": "01.02.2025",
        "baslik": "Örnek Yargıtay kararı",
        "chunk_metni": text,
        "chunk_metni_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "karakter_sayisi": len(text),
        "veri_kalite_uyarilari": [],
        "veri_kalite_durumu": "gecerli",
        "metin_2000_karakter_sinirinda": False,
        "kaynak": "test-corpus",
        "kaynak_url": "https://example.test/corpus",
        "kaynak_lisans": "CC BY 4.0",
        "kaynak_kayit_id": f"source-{index}",
    }


def write_jsonl(path, records):
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


class Day15IndexingTests(unittest.TestCase):
    def run_indexing(self, root, records, client, qdrant, **overrides):
        source = root / "chunks.jsonl"
        if not source.exists():
            write_jsonl(source, records)
        arguments = {
            "expected_chunk_count": len(records),
            "batch_size": 2,
            "max_attempts": 2,
            "retry_delay_seconds": 0,
            "expected_vector_size": 3,
            "collection_name": "day15_test",
            "embedding_client": client,
            "qdrant_client": qdrant,
            "sleep": lambda _: None,
        }
        arguments.update(overrides)
        return run_day15_indexing(
            source,
            root / "qdrant",
            root / "state.json",
            root / "report.json",
            root / "failures.jsonl",
            **arguments,
        )

    def test_batches_all_chunks_and_writes_verified_report(self):
        records = [chunk_record(index) for index in range(1, 6)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qdrant = QdrantClient(location=":memory:")
            client = FakeEmbeddingClient()
            progress = []
            try:
                report = self.run_indexing(
                    root,
                    records,
                    client,
                    qdrant,
                    progress_callback=lambda state: progress.append(
                        state["indexed_chunks"]
                    ),
                )
                saved_report = json.loads(
                    root.joinpath("report.json").read_text(encoding="utf-8")
                )
                saved_state = json.loads(
                    root.joinpath("state.json").read_text(encoding="utf-8")
                )
                second_client = FakeEmbeddingClient()
                repeated_report = self.run_indexing(
                    root,
                    records,
                    second_client,
                    qdrant,
                )
            finally:
                qdrant.close()

        self.assertEqual([len(batch) for batch in client.batches], [2, 2, 1])
        self.assertEqual(progress, [2, 4, 5])
        self.assertEqual(report, saved_report)
        self.assertTrue(saved_state["completed"])
        self.assertEqual(report["summary"]["indexed_chunks"], 5)
        self.assertEqual(report["qdrant"]["count_after_run"], 5)
        self.assertEqual(report["batch_processing"]["unresolved_failed_batches"], 0)
        self.assertTrue(report["verification"]["all_sample_hashes_match"])
        self.assertEqual(repeated_report, report)
        self.assertEqual(second_client.batches, [])

    def test_resumes_from_first_uncommitted_line_without_duplicates(self):
        records = [chunk_record(index) for index in range(1, 6)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qdrant = QdrantClient(location=":memory:")
            first_client = FakeEmbeddingClient()
            second_client = FakeEmbeddingClient()
            try:
                partial = self.run_indexing(
                    root,
                    records,
                    first_client,
                    qdrant,
                    max_batches=1,
                )
                report = self.run_indexing(root, records, second_client, qdrant)
            finally:
                qdrant.close()

        self.assertFalse(partial["completed"])
        self.assertEqual(partial["indexed_chunks"], 2)
        self.assertEqual(first_client.batches[0], [
            records[0]["chunk_metni"],
            records[1]["chunk_metni"],
        ])
        self.assertEqual(second_client.batches[0], [
            records[2]["chunk_metni"],
            records[3]["chunk_metni"],
        ])
        self.assertEqual(report["summary"]["indexed_chunks"], 5)
        self.assertEqual(report["qdrant"]["count_after_run"], 5)

    def test_failed_batch_is_logged_and_not_skipped_then_can_resume(self):
        records = [chunk_record(index) for index in range(1, 4)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qdrant = QdrantClient(location=":memory:")
            try:
                with self.assertRaisesRegex(Day15IndexingError, "after 2 attempts"):
                    self.run_indexing(
                        root,
                        records,
                        FailingEmbeddingClient(),
                        qdrant,
                    )
                failed_state = json.loads(
                    root.joinpath("state.json").read_text(encoding="utf-8")
                )
                failures = [
                    json.loads(line)
                    for line in root.joinpath("failures.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                ]
                recovered_client = FakeEmbeddingClient()
                report = self.run_indexing(
                    root,
                    records,
                    recovered_client,
                    qdrant,
                )
            finally:
                qdrant.close()

        self.assertEqual(failed_state["next_line"], 0)
        self.assertEqual(failed_state["failed_attempts"], 2)
        self.assertEqual(len(failures), 2)
        self.assertEqual(failures[0]["chunk_ids"], [
            records[0]["id"],
            records[1]["id"],
        ])
        self.assertEqual(recovered_client.batches[0][0], records[0]["chunk_metni"])
        self.assertEqual(report["batch_processing"]["failed_attempts"], 2)
        self.assertEqual(report["batch_processing"]["unresolved_failed_batches"], 0)

    def test_rejects_source_corruption_duplicates_and_wrong_count(self):
        records = [chunk_record(1), chunk_record(2)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "chunks.jsonl"

            write_jsonl(source, records)
            with self.assertRaisesRegex(Day15IndexingError, "count mismatch"):
                scan_chunk_source(
                    source,
                    expected_chunk_count=3,
                    embedding_model="test-embedding-model",
                    vector_size=3,
                )

            write_jsonl(source, [records[0], records[0]])
            with self.assertRaisesRegex(Day15IndexingError, "Duplicate chunk id"):
                scan_chunk_source(
                    source,
                    expected_chunk_count=2,
                    embedding_model="test-embedding-model",
                    vector_size=3,
                )

            corrupt = dict(records[0], chunk_metni_sha256="wrong")
            write_jsonl(source, [corrupt])
            with self.assertRaisesRegex(Day15IndexingError, "text hash mismatch"):
                scan_chunk_source(
                    source,
                    expected_chunk_count=1,
                    embedding_model="test-embedding-model",
                    vector_size=3,
                )

    def test_rejects_resume_with_changed_batch_configuration(self):
        records = [chunk_record(index) for index in range(1, 4)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qdrant = QdrantClient(location=":memory:")
            try:
                self.run_indexing(
                    root,
                    records,
                    FakeEmbeddingClient(),
                    qdrant,
                    max_batches=1,
                )
                with self.assertRaisesRegex(
                    Day15IndexingError, "configuration mismatch"
                ):
                    self.run_indexing(
                        root,
                        records,
                        FakeEmbeddingClient(),
                        qdrant,
                        batch_size=1,
                    )
            finally:
                qdrant.close()

    def test_allows_final_verification_to_resume_after_last_batch(self):
        records = [chunk_record(index) for index in range(1, 4)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "chunks.jsonl"
            state_path = root / "state.json"
            write_jsonl(source_path, records)
            source = scan_chunk_source(
                source_path,
                expected_chunk_count=3,
                embedding_model="test-embedding-model",
                vector_size=3,
            )
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source_sha256": source["sha256"],
                        "source_records": 3,
                        "batch_size": 2,
                        "collection_name": "day15_test",
                        "embedding_model": "test-embedding-model",
                        "vector_size": 3,
                        "next_line": 3,
                        "indexed_chunks": 3,
                        "successful_batches": 2,
                        "failed_attempts": 0,
                        "elapsed_seconds": 1.0,
                        "completed": False,
                        "last_completed_at": "2026-01-01T00:00:00+00:00",
                        "last_error": None,
                    }
                ),
                encoding="utf-8",
            )

            state = load_index_state(
                state_path,
                source,
                batch_size=2,
                collection_name="day15_test",
                embedding_model="test-embedding-model",
                vector_size=3,
            )

        self.assertFalse(state["completed"])
        self.assertEqual(state["next_line"], 3)


if __name__ == "__main__":
    unittest.main()
